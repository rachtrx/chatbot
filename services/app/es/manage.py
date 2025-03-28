from datetime import datetime
from elasticsearch import Elasticsearch, NotFoundError
from ._settings import index_body
from .file_extraction import read_pdf, read_word, read_txt
from azure.utils import generate_header
import requests
import os
import json
import re
import logging
from logs.config import setup_logger

es = Elasticsearch(
    ["https://es01:9200"],
    http_auth=("elastic", os.environ.get('ELASTIC_PASSWORD')),
    verify_certs=True,
    ca_certs=os.environ.get('ES_CA_CERTS')
)

logger = setup_logger('es.manage', 'es')

index_name = "sharepoint_docs"

def create_index():
    if not es.indices.exists(index=index_name):
        # Create the index if it doesn't exist
        logger.info("creating index")
        response = es.indices.create(index=index_name, body=index_body)
        logger.info(f"Index created: {response}")
    else:
        logger.info("Index already exists")

def process_text_to_sentences(text):
    # Replace newline characters with spaces
    text = text.replace('\n', ' ').replace('\t', ' ')
    text = text.replace('e.g.', 'eg')
    text = re.sub(r'\s{2,}', ' ', text)

    # Split the text into sentences based on full stops
    sentences = text.split('. ')

    # Remove any leading/trailing whitespace from each sentence
    sentences = [sentence.strip() for sentence in sentences if sentence.strip()]

    # Format each sentence as a dictionary
    formatted_sentences = [{"sentence": sentence, "sentence_no": index + 1}
                           for index, sentence in enumerate(sentences)]

    return formatted_sentences

def index_document(fileobj, text, keywords, index = index_name):
    """
    Index a document in Elasticsearch
    """
    doc_id = fileobj["id"]
    exists = get_document(index_name, doc_id)

    if exists:
        return
        logger.info("doc exists!")
    else:
        logger.info("doc doesn't exist!")

    doc = construct_document(fileobj)

    doc["content"] = process_text_to_sentences(text) # set the content to be the text
    doc["keywords"] = ' '.join(keywords)

    if not exists:
        
        resp = es.index(index=index, id=doc_id, document=doc)
        logger.info(f"Indexed result: {resp['result']}")

    else:
        update_document(doc_id, doc)

    logger.info("successfully indexed!")

def update_document(doc_id, updated_doc, index=index_name):
    """
    Update a document in Elasticsearch
    """
    es.update(index=index, id=doc_id, doc=updated_doc)

def delete_document(index, doc_id):
    """
    Delete a document from Elasticsearch
    """
    es.delete(index=index, id=doc_id)

def search_documents(index, query):
    """
    Search for documents in Elasticsearch
    """
    body = {
        "query": {
            "bool": {
                "should": [
                    {"nested": {
                        "path": "content",
                        "query": {"match": {"content.sentence": query}},
                        "inner_hits": {}
                     }},
                    {"match": {"keywords": {"query": query, "boost": 2.0}}}
                ],
                "minimum_should_match": 1
            }
        }
    }
    return es.search(index=index, body=body)

def get_document(index, doc_id):
    try:
        resp = es.get(index=index, id=doc_id)

        # logger.info(resp['_source'])
        return True
    except NotFoundError:
        logger.info(f"Document with ID {doc_id} not found in index {index}.")
        return False
    except Exception as e:
        logger.info(f"An error occurred: {e}")
        return False

def refresh_index(index):
    es.indices.refresh(index=index)

def read_document(stream, filename):
    keywords = []
    if filename.endswith(".pdf"):
        text, keywords = read_pdf(stream)
    elif filename.endswith(".docx"):
        text = read_word(stream)
    elif filename.endswith(".txt"):
        text = read_txt(stream)
    return (text, keywords)

def loop_through_files(url, fileobj=None):

    logger.info("looping")

    headers = generate_header()

    response = requests.get(url=url, headers=headers)
    # response.raise_for_status()
    if not 200 <= response.status_code < 300:
        logger.info("something went wrong when getting files")
        return

    if fileobj:
        filename = fileobj["name"]
        text, keywords = read_document(response.content, filename)
        index_document(fileobj, text, keywords)
        return
    
    for value in response.json()['value']:
        new_fileobj = None
        relevant = 1
        if value['name'].endswith(".pdf") or value['name'].endswith(".docx") or value['name'].endswith(".txt"):
            new_fileobj = value
            new_url = value['@microsoft.graph.downloadUrl']
        elif value.get('folder'):
            new_url = url[:-len(':/children')] + '/' + value['name'] + ':/children'
        else:
            relevant = 0
        
        if relevant:
            loop_through_files(new_url, new_fileobj)

# Example Usage
def construct_document(fileobj):
    doc = {
        "file": {
            "filename": fileobj["name"],
            "filesize": fileobj["size"],
            "indexing_date": datetime.now(),
            "created": fileobj["createdDateTime"],
            "author": fileobj["createdBy"]["user"]["displayName"],
            "last_modified": fileobj["lastModifiedDateTime"],
            "modifier": fileobj["lastModifiedBy"]["user"]["displayName"],
            "url": fileobj["webUrl"],
            "folder_path": fileobj["parentReference"]["path"]
        }
    }

    logger.info(f"filename: {fileobj['name']}")

    return doc

def search_for_document(query):
# Search for documents
    response = search_documents(index_name, query)
    # Assuming you are interested in the first hit's surrounding sentences

    result = []

    max_score = 0
    best_doc = None
    for doc in response['hits']['hits']:
        if 'inner_hits' in doc and 'content' in doc.get('inner_hits'):
            for inner_hit in doc['inner_hits']['content']['hits']['hits']:
                if inner_hit['_score'] > max_score:
                    max_score = inner_hit['_score']
                    best_doc = doc
                    top_sentence_no = inner_hit['_source']['sentence_no']
        else:
            logger.info("No matching documents found.")

    # Logic to find surrounding sentence numbers
    prev_sentence_no = max(1, top_sentence_no - 1)
    next_sentence_no = top_sentence_no + 1

    sentences = best_doc['_source']['content']

    # Find the sentences
    prev_sentence = next((s["sentence"] for s in sentences if s['sentence_no'] == prev_sentence_no), None)
    current_sentence = next((s["sentence"] for s in sentences if s['sentence_no'] == top_sentence_no), None)
    next_sentence = next((s["sentence"] for s in sentences if s['sentence_no'] == next_sentence_no), None)

    logger.info("Previous:", prev_sentence)
    logger.info("Current:", current_sentence)
    logger.info("Next:", next_sentence)
    
    data = " ".join([prev_sentence, current_sentence, next_sentence])
    result.append((data, best_doc['_source']['file']['filename'], best_doc['_source']['file']['url']))           

    # consider the filename if the score is too low?         

    return result
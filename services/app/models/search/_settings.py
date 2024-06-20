index_body = {
    "settings": {
        "number_of_shards": 1,
        "index.mapping.total_fields.limit": 2000,
        "analysis": {
            "analyzer": {
                "path_tokenizer": {
                    "tokenizer": "path_tokenizer"
                },
                "custom_search_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "stop"]
                }
            },
            "tokenizer": {
                "path_tokenizer": {
                    "type": "path_hierarchy"
                }
            }
        }
    },
    "mappings": {
        "properties": {
            "content": {
                "type": "nested",
                "properties": {
                    "sentence": {
                        "type": "text",
                        "analyzer": "standard",
                        "search_analyzer": "custom_search_analyzer",
                    },
                    "sentence_no": {
                        "type": "integer"
                    }
                }
            },
            "keywords": {
                "type": "text"
            },
            "file": {
                "properties": {
                    "filename": {
                        "type": "keyword",
                        # "store": True
                    },
                    "filesize": {
                        "type": "long"
                    },
                    "indexing_date": {
                        "type": "date",
                        "format": "date_optional_time"
                    },
                    "created": {
                        "type": "date",
                        "format": "date_optional_time"
                    },
                    "author": {
                        "type": "text"
                    },
                    "last_modified": {
                        "type": "date",
                        "format": "date_optional_time"
                    },
                    "modifier": {
                        "type": "text"
                    },
                    "url": {
                        "type": "keyword",
                        "index": False
                    },
                    "folder_path": {
                        "type": "keyword",
                        "fields": {
                            "tree": {
                                "type": "text",
                                "analyzer": "path_tokenizer",
                                # "fielddata": True
                            },
                            "fulltext": {
                                "type": "text"
                            }
                        }
                    },
                }
            },
        }
    }
}



# index_body = {
#     "settings": {
#         "number_of_shards": 1,
#         "index.mapping.total_fields.limit": 2000,
#         "analysis": {
#             "analyzer": {
#                 "fscrawler_path": {
#                 "tokenizer": "fscrawler_path"
#                 }
#             },
#             "tokenizer": {
#                 "fscrawler_path": {
#                 "type": "path_hierarchy"
#                 }
#             }
#         }
#     },
#     "mappings": {
#         "properties": {
#             "attachment": {
#                 "type": "binary",
#                 "doc_values": False
#             },
#             "attributes": {
#                 "properties": {
#                     "group": {
#                         "type": "keyword"
#                     },
#                     "owner": {
#                         "type": "keyword"
#                     }
#                 }
#             },
#             "content": {
#                 "type": "text"
#             },
#             "file": {
#                 "properties": {
#                     "content_type": {
#                         "type": "keyword"
#                     },
#                     "filename": {
#                         "type": "keyword",
#                         "store": True
#                     },
#                     "extension": {
#                         "type": "keyword"
#                     },
#                     "filesize": {
#                         "type": "long"
#                     },
#                     "indexed_chars": {
#                         "type": "long"
#                     },
#                     "indexing_date": {
#                         "type": "date",
#                         "format": "date_optional_time"
#                     },
#                     "created": {
#                         "type": "date",
#                         "format": "date_optional_time"
#                     },
#                     "last_modified": {
#                         "type": "date",
#                         "format": "date_optional_time"
#                     },
#                     "last_accessed": {
#                         "type": "date",
#                         "format": "date_optional_time"
#                     },
#                     "checksum": {
#                         "type": "keyword"
#                     },
#                     "url": {
#                         "type": "keyword",
#                         "index": False
#                     }
#                 }
#             },
#             "meta": {
#                 "properties": {
#                     "author": {
#                         "type": "text"
#                     },
#                     "date": {
#                         "type": "date",
#                         "format": "date_optional_time"
#                     },
#                     "keywords": {
#                         "type": "text"
#                     },
#                     "title": {
#                         "type": "text"
#                     },
#                     "language": {
#                         "type": "keyword"
#                     },
#                     "format": {
#                         "type": "text"
#                     },
#                     "identifier": {
#                         "type": "text"
#                     },
#                     "contributor": {
#                         "type": "text"
#                     },
#                     "coverage": {
#                         "type": "text"
#                     },
#                     "modifier": {
#                         "type": "text"
#                     },
#                     "creator_tool": {
#                         "type": "keyword"
#                     },
#                     "publisher": {
#                         "type": "text"
#                     },
#                     "relation": {
#                         "type": "text"
#                     },
#                     "rights": {
#                         "type": "text"
#                     },
#                     "source": {
#                         "type": "text"
#                     },
#                     "type": {
#                         "type": "text"
#                     },
#                     "description": {
#                         "type": "text"
#                     },
#                     "created": {
#                         "type": "date",
#                         "format": "date_optional_time"
#                     },
#                     "print_date": {
#                         "type": "date",
#                         "format": "date_optional_time"
#                     },
#                     "metadata_date": {
#                         "type": "date",
#                         "format": "date_optional_time"
#                     },
#                     "latitude": {
#                         "type": "text"
#                     },
#                     "longitude": {
#                         "type": "text"
#                     },
#                     "altitude": {
#                         "type": "text"
#                     },
#                     "rating": {
#                         "type": "byte"
#                     },
#                     "comments": {
#                         "type": "text"
#                     }
#                 }
#             },
#             "path": {
#                 "properties": {
#                     "real": {
#                         "type": "keyword",
#                         "fields": {
#                             "tree": {
#                                 "type": "text",
#                                 "analyzer": "fscrawler_path",
#                                 "fielddata": True
#                             },
#                             "fulltext": {
#                                 "type": "text"
#                             }
#                         }
#                     },
#                     "root": {
#                         "type": "keyword"
#                     },
#                     "virtual": {
#                         "type": "keyword",
#                         "fields": {
#                             "tree": {
#                                 "type": "text",
#                                 "analyzer": "fscrawler_path",
#                                 "fielddata": True
#                             },
#                             "fulltext": {
#                                 "type": "text"
#                             }
#                         }
#                     }
#                 }
#             }
#         }
#     }
# }


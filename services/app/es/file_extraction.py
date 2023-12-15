import docx
import sys, pathlib, fitz
import io
import numpy as np
import pandas as pd

# To analyze the PDF layout and extract text
from pdfminer.high_level import extract_pages, extract_text
from pdfminer.layout import LTTextContainer, LTChar, LTRect, LTFigure
# To extract text from tables in PDF
import pdfplumber
# To extract the images from the PDFs
from PIL import Image
# To perform OCR to extract text from images 
import pytesseract 
import requests
import spacy

def is_bold(font_name):
    return "Bold" in font_name or "Bd" in font_name

def process_text_element(element):

    line_text = ""
    current_word = ""
    sum_words_font_size = 0
    word_count = 0
    current_word_bold = False

    # if isinstance(element, LTTextContainer):
    #     # Iterating through each character in the line of text
    for text_line in element:
        if isinstance(text_line, LTTextContainer):  # Check if it's a text line
            for character in text_line:
                if isinstance(character, LTChar):
                    current_word += character.get_text()
            
                    # Check for bold
                    if is_bold(character.fontname):
                        current_word_bold = True

                    # Store font size
                    current_font_size = round(character.size)

                if character.get_text().isspace():
                    # Space encountered, word ends
                    if current_word:
                        word_count += 1
                        sum_words_font_size += current_font_size
                        line_text += current_word + " "
                        yield [current_word, current_font_size, current_word_bold]
                    
                    # Reset for next word
                    current_word = ""
                    current_font_size = []
                    current_word_bold = False

    return [sum_words_font_size, word_count]

def extract_table(pdf_path, page_num, table_num):
    # Open the pdf file
    pdf = pdfplumber.open(pdf_path)
    # Find the examined page
    table_page = pdf.pages[page_num]
    # Extract the appropriate table
    table = table_page.extract_tables()[table_num]
    return table

# Convert table into the appropriate format
def table_converter(table):
    table_string = ''
    # Iterate through each row of the table
    for row_num in range(len(table)):
        row = table[row_num]
        # Remove the line breaker from the wrapped texts
        cleaned_row = [item.replace('\n', ' ') if item is not None and '\n' in item else 'None' if item is None else item for item in row]
        # Convert the table into a string 
        table_string+=('|'+'|'.join(cleaned_row)+'|'+'\n')
    # Removing the last line break
    table_string = table_string[:-1]
    return table_string

def crop_image_to_text(element, page):
    # Get the coordinates to crop the image from the PDF
    [x0, y0, x1, y1] = [element.x0, element.y0, element.x1, element.y1]

    # Define the rectangle to crop
    clip_rect = fitz.Rect(x0, y0, x1, y1)

    # Crop the page to the size of the image
    pix = page.get_pixmap(clip=clip_rect)

    # Convert the pixmap to an image
    img_data = pix.tobytes("png")  # Convert the image to PNG bytes
    img = Image.open(io.BytesIO(img_data))
    text = pytesseract.image_to_string(img)
    return text

def get_keywords(words_info):
    words_df = pd.DataFrame(data = words_info, columns = ["word", "font_size", "bold"])

    words_df = words_df.replace(' ', np.nan).dropna().reset_index(drop=True)
    words_df['font_size'] = words_df.apply(lambda x: x['font_size'] * 2 if x['bold'] else x['font_size'], axis=1)
    words_df = words_df.reset_index().rename(columns={'index': 'seq_no'})

    # Group by font size and count the occurrences
    font_size_group = words_df.groupby('font_size').size().reset_index(name='counts')

    # Calculate the proportion of each font size
    total_words = font_size_group['counts'].sum()
    font_size_group['proportion'] = (font_size_group['counts'] / total_words) * 100

    # Sort by counts to get the less common font sizes
    font_size_group_sorted = font_size_group.sort_values(by='font_size', ascending=False)

    font_size_group_sorted['cumulative_proportion'] = font_size_group_sorted['proportion'].cumsum()

    # Define a threshold for the maximum proportion you consider significant
    threshold = 20  # This means we consider font sizes that constitute less than 5% of the document

    # Filter the DataFrame to get font sizes whose cumulative proportion is under the threshold
    significant_font_sizes = font_size_group_sorted[font_size_group_sorted['cumulative_proportion'] <= threshold]

    final_keywords_arr = []

    if not significant_font_sizes.empty:
        # Extract the list of significant font sizes
        significant_sizes = significant_font_sizes['font_size'].tolist()

        # Filter the original DataFrame to only include rows with significant font sizes
        keywords_df = words_df[words_df['font_size'].isin(significant_sizes)]

        # Iterate through the DataFrame rows
        keywords_arr = keywords_df['word'].str.strip().to_numpy()

        nlp = spacy.load("en_core_web_sm")

        doc = nlp(str(' '.join(keywords_arr)))

        final_keywords_arr = set(token.text.lower() for token in doc if not token.is_stop and 
                                                              not token.like_num and 
                                                              token.is_alpha and 
                                                              token.ent_type_ not in ['DATE', 'TIME'])

        final_keywords_arr = list(final_keywords_arr)

    return final_keywords_arr

def read_pdf(stream):

    # Create the dictionary to extract text from each image
    # text_per_page = {}

    doc = fitz.open(stream=stream, filetype="pdf")

    # Open the pdf file
    pdf_stream = io.BytesIO(stream)
    pdf = pdfplumber.open(pdf_stream)

    doc_content = []

    words_info = []
    sum_words_font_size = 0
    word_count = 0
    
    # We extract the pages from the PDF
    for pagenum, page in enumerate(extract_pages(pdf_stream)):
        
        # Initialize the variables needed for the text extraction from the page
        fitz_page = doc.load_page(pagenum)

        table_num = 0
        first_element= True
        table_extraction_flag= False
        
        # Find the examined page
        page_tables = pdf.pages[pagenum]
        # Find the number of tables on the page
        tables = page_tables.find_tables()


        # Find all the elements
        page_elements = [(element.y1, element) for element in page._objs]
        # Sort all the elements as they appear in the page 
        page_elements.sort(key=lambda a: a[0], reverse=True)

        lower_side = upper_side = None

        # Find the elements that composed a page
        for i, component in enumerate(page_elements):
            # Extract the element of the page layout
            element = component[1]
            
            # Check if the element is a text element

            if isinstance(element, LTTextContainer):
                # Check if the text appeared in a table
                if table_extraction_flag == False:
                    # Use the function to extract the text and format for each text element
                    generator = process_text_element(element)

                    try:
                        while True:
                            # Process each yielded value
                            word_info = next(generator)
                            # Do something with word_info
                            doc_content.append(word_info[0])
                            words_info.append(word_info)
                    except StopIteration as e:
                        # Catch the return value from the generator
                        sum_words_font_size += e.value[0]
                        word_count += e.value[1]

                else:
                    # Omit the text that appeared in a table
                    pass

            # Check the elements for images
            if isinstance(element, LTFigure):
                # Crop the image from the PDF
                image_text = crop_image_to_text(element, fitz_page)
                # text_from_images.append(image_text)
                doc_content.append(image_text)

            # Check the elements for tables
            if isinstance(element, LTRect):
                # If the first rectangular element
                if first_element == True and (table_num + 1) <= len(tables):
                    # Find the bounding box of the table
                    lower_side = page.bbox[3] - tables[table_num].bbox[3]
                    upper_side = element.y1 
                    # Extract the information from the table
                    table = extract_table(pdf_stream, pagenum, table_num)
                    # Convert the table information in structured string format
                    table_string = table_converter(table)
                    # Append the table string into a list
                    # text_from_tables.append(table_string)
                    doc_content.append(table_string)
                    # Set the flag as True to avoid the content again
                    table_extraction_flag = True
                    # Make it another element
                    first_element = False

                # Check if we already extracted the tables from the page
                if lower_side and upper_side and element.y0 >= lower_side and element.y1 <= upper_side:
                    pass
                elif i + 1 < len(page_elements) and not isinstance(page_elements[i+1][1], LTRect):
                    table_extraction_flag = False
                    first_element = True
                    table_num += 1

    # Closing the pdf file object
    doc.close()

    text = ''.join(doc_content)

    # print(f"text: {text}")

    # print(word_info[0] for word_info in words_info)

    keywords_arr = get_keywords(words_info)

    return text, keywords_arr

def read_word(content):
    file_stream = io.BytesIO(content)
    doc = docx.Document(file_stream)
    text = ""
    for paragraph in doc.paragraphs:
        text += paragraph.text + "\n"
    text += "\n"
    return text

def read_txt(content):
    text = content.decode('utf-16')
    text += "\n"
    return text


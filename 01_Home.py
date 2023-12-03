import streamlit as st
import re
from PyPDF2 import PdfReader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.chat_models import ChatOpenAI
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA
from langchain.vectorstores import FAISS

def get_chunks(file_input : list, use_splitter = True, 
                     remove_leftover_delimiters = True,
                     remove_pages = False,
                     chunk_size=800, chunk_overlap=80,
                     front_pages_to_remove : int = None, last_pages_to_remove : int = None, 
                     delimiters_to_remove : list = ['\t', '\n', '   ', '  ']):
    
    # Main list of all LangChain Documents
    documents = []
    document_names = []
    print(f'Splitting documents: total of {len(file_input)}')

    # Handle file by file
    for file_index, file in enumerate(file_input):
        reader = PdfReader(file)
        print(f'\tOriginal pages of document {file_index+1}: {len(reader.pages)}')
        pdf_title = 'uploaded_file_' + str(file_index+1)
        for key, value in reader.metadata.items():
            if 'title' in key.lower():
                pdf_title = value
        document_names.append(pdf_title)
                
        # Remove pages
        if remove_pages:
            for _ in range(front_pages_to_remove):
                del reader.pages[0]
            for _ in range(last_pages_to_remove):
                reader.pages.pop()
            print(f'\tNumber of pages after skipping: {len(reader.pages)}')

        # Each file will be split into LangChain Documents and kept in a list
        document = []

        # Loop through each page and extract the text and write in metadata
        if use_splitter:
            splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size,
                                                chunk_overlap=chunk_overlap,
                                                separators = ['\n\n', ' '])
            for page_number, page in enumerate(reader.pages):
                page_chunks = splitter.split_text(page.extract_text()) # splits into a list of strings (chunks)

                # Write into Document format with metadata
                for chunk in page_chunks:
                    document.append(Document(page_content=chunk, 
                                             metadata={'source': pdf_title , 'page':str(page_number+1)}))
            
        else:
            # This will split purely by page
            for page_number, page in enumerate(reader.pages):
                document.append(Document(page_content=page.extract_text(), 
                                      metadata={'source': pdf_title , 'page':str(page_number+1)}))
                i += 1
        

        # Remove all left over the delimiters and extra spaces
        if remove_leftover_delimiters:
            for chunk in document:
                for delimiter in delimiters_to_remove:
                    chunk.page_content = re.sub(delimiter, ' ', chunk.page_content)

        documents.extend(document)

    print(f'Number of document chunks extracted: {len(documents)}')
    return documents, document_names

def get_embeddings(openai_api_key : str, documents : list,  db_option : str = 'FAISS', persist_directory : str = None ):
    # create the open-source embedding function
    embedding_function = OpenAIEmbeddings(deployment="SL-document_embedder",
                                        model='text-embedding-ada-002',
                                        show_progress_bar=True,
                                        openai_api_key = openai_api_key) 

    # load it into FAISS
    print('Initializing vector_db')
    if db_option == 'FAISS':
        if persist_directory:
            vector_db = FAISS.from_documents(documents = documents, 
                                            embedding = embedding_function,
                                            persist_directory = persist_directory)    
        else:
            vector_db = FAISS.from_documents(documents = documents, 
                                            embedding = embedding_function)
    print('\tCompleted')
    return vector_db

def get_llm(openai_api_key, temperature, model_name = 'gpt-3.5-turbo-1106'):
    # Instantiate the llm object 
    print('Instantiating the llm')
    try:
        llm = ChatOpenAI(model_name=model_name, 
                        temperature=temperature, 
                        api_key=openai_api_key)
    except Exception as e:
        print(e)
        st.error('Error occured, check that your API key is correct.', icon="🚨")
    else:
        print('\tCompleted')
    return llm 

def get_chain(llm, vector_db, prompt_mode):
    print('Creating chain from template')
    if prompt_mode == 'Restricted':
        # Build prompt template
        template = """Use the following pieces of context to answer the question at the end. \
        If you don't know the answer, just say that you don't know, don't try to make up an answer. \
        Keep the answer as concise as possible. 
        Context: {context}
        Question: {question}
        Helpful Answer:"""
        qa_chain_prompt = PromptTemplate.from_template(template)
    elif prompt_mode == 'Creative':
        # Build prompt template
        template = """Use the following pieces of context to answer the question at the end. \
        If you don't know the answer, you may make inferences, but make it clear in your answer. \
        Keep the answer as concise as possible. 
        Context: {context}
        Question: {question}
        Helpful Answer:"""
        qa_chain_prompt = PromptTemplate.from_template(template)

    # Build QuestionAnswer chain
    qa_chain = RetrievalQA.from_chain_type(
        llm,
        retriever=vector_db.as_retriever(),
        return_source_documents=True,
        chain_type_kwargs={"prompt": qa_chain_prompt}
        )
    print('\tCompleted')
    return qa_chain

def get_response(user_input, qa_chain):
    # Query and Response
    print('Getting response from server')
    result = qa_chain({"query": user_input})
    return result
    
def main():
  '''
  Main Function
  '''
  st.set_page_config(page_title="Document Query Bot ")
  result = None
  if 'doc_names' not in st.session_state:
    st.session_state.doc_names = None
    

  # Sidebar
  with st.sidebar:
    openai_api_key =st.text_input("Enter your API key")
    documents = st.file_uploader(label = 'Upload documents for embedding to VectorDB', 
                                  help = 'Overwrites an existing files uploaded',
                                  type = ['pdf'], 
                                  accept_multiple_files=True)
    if st.button('Upload', type='primary') and documents:
      with st.status('Uploading... (this may take a while)', expanded=True) as status:
          try:
            st.write("Splitting documents...")
            docs, st.session_state.doc_names = get_chunks(documents)
            st.write("Creating embeddings...")
            st.session_state.vector_db = get_embeddings(openai_api_key, docs, persist_directory=None)
          except Exception as e:
            print(e)
            status.update(label='Error occured.', state='error', expanded=False)
          else:
            status.update(label='Embedding complete!', state='complete', expanded=False)

  # Main page area
  st.markdown("### :rocket: Welcome to Sien Long's Document Query Bot")
  st.info(f"Current loaded document(s) \n\n {st.session_state.doc_names}", icon='ℹ️')
  st.write('Enter your API key on the sidebar to begin')

  # Query form and response
  with st.form('my_form'):
    user_input = st.text_area('Enter prompt:', 'What are the documents about and who are the authors?')

    # Select for model and prompt template settings
    if st.session_state.doc_names:
        prompt_mode = st.selectbox('Choose mode of prompt', ('Restricted', 'Creative'), help='Restriced mode will reduce chances of using outside sources')
        temperature = st.select_slider('Select temperature', options=[x / 10 for x in range(0, 21)], help='Lower = generate more likely next words, higher = generate less likely next words')
    
    # Display error if no API key given
    if not openai_api_key.startswith('sk-'):
      st.warning('Please enter your OpenAI API key!', icon='⚠')

    # Submit a prompt
    if st.form_submit_button('Submit', type='primary') and openai_api_key.startswith('sk-'):
        with st.spinner('Loading...'):
            try:
                st.session_state.llm = get_llm(openai_api_key, temperature, model_name = 'gpt-3.5-turbo-1106')
                st.session_state.qa_chain = get_chain(st.session_state.llm, st.session_state.vector_db, prompt_mode)
                result = get_response(user_input, st.session_state.qa_chain)
            except Exception as e:
                print(e)
                st.error('Error occured, unable to process response!', icon="🚨")

        if result:
            # Display the result
            st.info('Query Response:', icon='📕')
            st.info(result["result"])
            st.write(' ')
            st.info('Sources', icon='📚')
            for document in result['source_documents']:
                st.write(document.page_content + '\n\n' + document.metadata['source'] + ' (pg ' + document.metadata['page'] + ')')
                st.write('-----------------------------------')
            print('\tCompleted')

# Main
if __name__ == '__main__':
   main()

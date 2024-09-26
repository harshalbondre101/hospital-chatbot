from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.responses import HTMLResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from datetime import datetime
from pydantic import BaseModel
import uuid
import yaml
import os
import chromadb
from llama_index.core import VectorStoreIndex, StorageContext, get_response_synthesizer
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.llms.openai import OpenAI
from llama_index.core.tools import QueryEngineTool, FunctionTool
from llama_index.agent.openai import OpenAIAssistantAgent
from events import *
from fastapi.middleware.cors import CORSMiddleware
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.core.postprocessor import SimilarityPostprocessor
from llama_index.core.response_synthesizers import BaseSynthesizer
from llama_index.core.query_engine import CustomQueryEngine
from llama_index.core.retrievers import BaseRetriever
from llama_index.core import Settings

# setting llm to gpt-4o
#Settings.llm = OpenAI(temperature=0.2, model="gpt-4o", default_headers={"OpenAI-Beta": "assistants=v2"})

import nest_asyncio

# Apply the nest_asyncio patch
nest_asyncio.apply()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

chatbots = {}

with open("global_config.yaml", "r") as f:
        config = yaml.safe_load(f)

# updated timezone
DEFAULT_TIMEZONE_OFFSET = config['google_calendar_config']['default_timezone_offset']
settimezone(DEFAULT_TIMEZONE_OFFSET)

class StartChatResponse(BaseModel):
    thread_id: str

class ChatRequest(BaseModel):
    thread_id: str
    message: str

class ChatResponse(BaseModel):
    response: str

class RAGQueryEngine(CustomQueryEngine):
    """RAG Query Engine."""

    retriever: BaseRetriever
    response_synthesizer: BaseSynthesizer

    def custom_query(self, query_str: str):
        nodes = self.retriever.retrieve(query_str)
        response_obj = self.response_synthesizer.synthesize(query_str, nodes)
        return response_obj

async def create_new_chatbot(user_id):
    # Function to create a new chatbot for a user
    with open("global_config.yaml", "r") as f:
        config = yaml.safe_load(f)
        #os.environ["OPENAI_API_KEY"] = config["OPENAI_API_KEY"]
        # Retrieve OpenAI API key from environment variable
        OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
        if not OPENAI_API_KEY:
            raise ValueError("OpenAI API key not set in environment variables")

    db = chromadb.PersistentClient(config["chroma_db_path"])
    chroma_collection = db.get_or_create_collection(config["collection_name"])
    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    index = VectorStoreIndex.from_vector_store(vector_store, storage_context=storage_context)

    llm = OpenAI(model=config["model"],temperature=config["temperature"],max_tokens=config["max_tokens"])

    retriever = VectorIndexRetriever(
            index=index,
            similarity_top_k=config["top_k"],
            llm=llm
        )
        # configure response synthesizer
    response_synthesizer = get_response_synthesizer()

    # assemble query engine
    query_engine = RAGQueryEngine(
        retriever=retriever,
        response_synthesizer=response_synthesizer,
        node_postprocessors=[SimilarityPostprocessor(similarity_cutoff=config["top_k"])],
    )

    chat_engine = QueryEngineTool.from_defaults(
        query_engine=query_engine,
        name="chat_engine",
        description="The chat engine helps users to solve hospital-related queries",
    )
    def get_todays_date():
        # Get today's date and weekday
        today_date = datetime.datetime.today().date()
        # Get the day of the week (Monday is 0, Sunday is 6)
        day_of_week = datetime.datetime.today().weekday()
        # Convert the day of the week to a string representation
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        day_name = days[day_of_week]
        return "Today's date is " + str(today_date) + " and the day of the week is " + str(day_name)

    get_list_of_available_slots_on_date_tool = FunctionTool.from_defaults(fn=get_list_of_available_slots_on_date)
    create_appointment_tool = FunctionTool.from_defaults(fn=create_appointment)
    delete_appointment_tool = FunctionTool.from_defaults(fn=delete_appointment)
    update_appointment_tool = FunctionTool.from_defaults(fn=update_appointment)
    get_events_by_user_email_tool = FunctionTool.from_defaults(fn=get_events_by_user_email)
    get_todays_date_tool = FunctionTool.from_defaults(fn=get_todays_date)

    hospital_agent = OpenAIAssistantAgent.from_new(
        name="hospital support chatbot",
        instructions=config["prompts"],
        tools=[chat_engine, get_list_of_available_slots_on_date_tool, create_appointment_tool, delete_appointment_tool,
               update_appointment_tool, get_events_by_user_email_tool, get_todays_date_tool],
        instructions_prefix="",
        files = None,
        verbose=True
    )
    thread_id = hospital_agent.thread_id
    # Store the chatbot instance with the thread_id as the key
    chatbots[thread_id] = hospital_agent

    # Create a folder for the user if it doesn't exist
    user_folder = f"chats/{thread_id}"
    os.makedirs(user_folder, exist_ok=True)

    # Store user_id, session_id, and thread_id in a text file
    with open(f"{user_folder}/user_info.txt", "a", errors="replace") as user_file:
        user_file.write(f"Thread ID: {hospital_agent.thread_id}\n\n")

    return hospital_agent.thread_id

async def run_chatbot(user_thread_id):
    # Function to run an existing chatbot for a user
    with open("global_config.yaml", "r") as f:
        config = yaml.safe_load(f)
        os.environ["OPENAI_API_KEY"] = config["OPENAI_API_KEY"]

    db = chromadb.PersistentClient(config["chroma_db_path"])
    chroma_collection = db.get_or_create_collection(config["collection_name"])
    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    index = VectorStoreIndex.from_vector_store(vector_store, storage_context=storage_context)

    llm = OpenAI(model=config["model"], temperature=config["temperature"], max_tokens=config["max_tokens"])

    retriever = VectorIndexRetriever(
            index=index,
            similarity_top_k=config["top_k"],
            llm=llm
        )
        # configure response synthesizer
    response_synthesizer = get_response_synthesizer()

    # assemble query engine
    query_engine = RAGQueryEngine(
        retriever=retriever,
        response_synthesizer=response_synthesizer,
        node_postprocessors=[SimilarityPostprocessor(similarity_cutoff=config["top_k"])],
    )

    chat_engine = QueryEngineTool.from_defaults(
        query_engine=query_engine,
        name="chat_engine",
        description="The chat engine helps users to solve hospital-related queries",
    )

    def get_todays_date():
        # Get today's date and weekday
        today_date = datetime.datetime.today().date()
        # Get the day of the week (Monday is 0, Sunday is 6)
        day_of_week = datetime.datetime.today().weekday()
        # Convert the day of the week to a string representation
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        day_name = days[day_of_week]
        return "Today's date is " + str(today_date) + " and the day of the week is " + str(day_name)

    get_list_of_available_slots_on_date_tool = FunctionTool.from_defaults(fn=get_list_of_available_slots_on_date)
    create_appointment_tool = FunctionTool.from_defaults(fn=create_appointment)
    delete_appointment_tool = FunctionTool.from_defaults(fn=delete_appointment)
    update_appointment_tool = FunctionTool.from_defaults(fn=update_appointment)
    get_events_by_user_email_tool = FunctionTool.from_defaults(fn=get_events_by_user_email)
    get_todays_date_tool = FunctionTool.from_defaults(fn=get_todays_date)

    hospital_agent = OpenAIAssistantAgent.from_new(
        name="hospital support chatbot",
        instructions=config["prompts"],
        tools=[chat_engine, get_list_of_available_slots_on_date_tool, create_appointment_tool, delete_appointment_tool,
               update_appointment_tool, get_events_by_user_email_tool, get_todays_date_tool],
        instructions_prefix="",
        verbose=True,
        files = None,
        thread_id=user_thread_id
    )

    return hospital_agent

@app.get('/start', response_model=StartChatResponse)
async def start_chat():
    user_id = str(uuid.uuid4())
    thread_id = await create_new_chatbot(user_id)
    if thread_id:
        return StartChatResponse(thread_id=thread_id)
    else:
        raise HTTPException(status_code=500, detail="Failed to create chatbot")

@app.post('/chat', response_model=ChatResponse)
async def chat(request: ChatRequest):
    thread_id = request.thread_id
    user_query = request.message

    chatbot = await run_chatbot(thread_id)
    if chatbot:
        response = chatbot.chat(user_query)
        response = str(response)

        # Store the chat log in a text file
        user_folder = f"chats/{chatbot.thread_id}"
        with open(f"{user_folder}/{thread_id}.txt", "a", errors="replace") as chat_file:
            chat_file.write(f"User: {user_query}\n")
            chat_file.write(f"Bot: {response}\n\n")

        return ChatResponse(response=response)
    else:
        raise HTTPException(status_code=400, detail="Invalid thread_id")



# Define FastAPI routes
@app.get("/", response_class=HTMLResponse)
async def read_index():
    return FileResponse("index.html")

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)

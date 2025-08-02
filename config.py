import os
import json
import base64
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv
import openai

# Load environment variables
load_dotenv()

# Database connection
DATABASE_URI = 'postgresql://adobi@localhost/adobi'
engine = create_engine(DATABASE_URI)
Session = sessionmaker(bind=engine)
session = Session()

# SQLAlchemy Base
Base = declarative_base()

# Define context storage model
class AgentContext(Base):
    __tablename__ = 'agent_contexts'
    id = Column(Integer, primary_key=True)
    agent_name = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    content = Column(Text, nullable=False)

# Define summaries model
class Summary(Base):
    __tablename__ = 'summaries'
    id = Column(Integer, primary_key=True)
    agent = Column(String, nullable=False)
    timestamp = Column(DateTime, nullable=False)
    run_id = Column(String, nullable=False)
    data = Column(Text, nullable=False)

# Create tables if not exist
Base.metadata.create_all(engine)

# OpenAI configuration
# api_key = os.getenv("OPENAI_API_KEY")
api_key= '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'
openai.api_key = api_key

# Define the global model to use
GPT_MODEL = "gpt-4.1"

class PromptManager:
    def __init__(self, client, session, run_id=None):
        self.client = client
        self.session = session
        self.run_id = run_id

    def ask_openai(self, prompt, system_prompt, agent_name=None, image_paths=None, max_retries=3):
        retries = 0
        while retries < max_retries:
            try:
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ]

                if image_paths:
                    for image_path in image_paths:
                        with open(image_path, "rb") as img_file:
                            image_bytes = img_file.read()
                        encoded_image = base64.b64encode(image_bytes).decode("utf-8")
                        messages.append({
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/png;base64,{encoded_image}"}
                                }
                            ]
                        })

                response = self.client.chat.completions.create(
                    model=GPT_MODEL,
                    messages=messages,
                    max_tokens=1000,
                    temperature=0.3,
                    #response_format="json",
                )
                content = response.choices[0].message.content.strip()

                # Save context
                #if agent_name:
                #    context_entry = Summary(agent=agent_name, timestamp=datetime.utcnow(), run_id=self.run_id or 'unspecified', data=json.dumps({"summary": content}))
                #    self.session.add(context_entry)
                #    self.session.commit()

                # Try parsing JSON
                return json.loads(content)

            except json.JSONDecodeError as e:
                print(f"JSON Decode Error: {e}")
                print(f"Response was: {content}")
                retries += 1

            except Exception as e:
                print(f"API Call Error: {e}")
                return {"error": "[API error, no response]"}

        return {"error": "Max retries reached, incomplete JSON response"}

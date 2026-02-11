
import logging
import asyncio
from ollama import Client as OllamaClient
from config import LLM_MODEL

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LLMProvider:
    """
    Unified LLM Provider - OLLAMA ONLY.
    Removed Gemini fallback as per user request.
    """
    
    def __init__(self):
        self.ollama_client = OllamaClient(host='http://localhost:11434')
        self.ollama_model = "llama3.2" # Default to llama3.2
        print(f"LLM Provider initialized with ONLY Ollama ({self.ollama_model})")
        
    async def generate(self, prompt: str, system_instruction: str = None) -> str:
        """
        Generate text using ONLY Ollama.
        """
        try:
            logger.info(f"Generating with Ollama ({self.ollama_model})...")
            
            def run_ollama():
                print(f"OLLAMA GENERATING: {prompt[:50]}...")
                if system_instruction:
                    messages = [
                        {'role': 'system', 'content': system_instruction},
                        {'role': 'user', 'content': prompt}
                    ]
                    # Chat endpoint
                    response = self.ollama_client.chat(model=self.ollama_model, messages=messages)
                    
                    # Robust response handling
                    try:
                        if hasattr(response, 'message'):
                            return response.message.content
                        if isinstance(response, dict) and 'message' in response:
                            return response['message']['content']
                        return str(response)
                    except Exception as e:
                        print(f"Ollama parsing error: {e}")
                        return str(response)
                else:
                    # Generate endpoint
                    response = self.ollama_client.generate(model=self.ollama_model, prompt=prompt)
                    if isinstance(response, dict):
                        return response['response']
                    else:
                        return response.response

            return await asyncio.to_thread(run_ollama)
                
        except Exception as e:
            print(f"Ollama Error: {e}")
            logger.error(f"Ollama generation failed: {e}")
            return f"I apologize, but I am unable to process your request at the moment. (Error: {str(e)})"

# Singleton instance
llm_provider = LLMProvider()

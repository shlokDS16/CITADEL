import logging
import asyncio
import google.generativeai as genai
from ollama import Client as OllamaClient
from config import LLM_MODEL, GOOGLE_API_KEY

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LLMProvider:
    """
    Unified LLM Provider - Hybrid Gemini + Ollama.
    Uses Gemini as Primary (Reliable for demo) and Ollama as Local Fallback.
    """
    
    def __init__(self):
        # Initialize Gemini
        if GOOGLE_API_KEY:
            genai.configure(api_key=GOOGLE_API_KEY)
            self.gemini_model = genai.GenerativeModel('gemini-1.5-flash')
            self.use_gemini = True
            print("LLM Provider initialized with Google Gemini (Primary)")
        else:
            self.use_gemini = False
            print("WARNING: GOOGLE_API_KEY missing. Falling back to Ollama.")

        # Initialize Ollama
        self.ollama_client = OllamaClient(host='http://localhost:11434')
        self.ollama_model = "llama3.2" 
        
    async def generate(self, prompt: str, system_instruction: str = None) -> str:
        """
        Generate text using Gemini (Primary) or Ollama (Secondary).
        """
        # 1. Try Gemini (Primary)
        if self.use_gemini:
            try:
                logger.info(f"Generating with Gemini (1.5 Flash)...")
                
                def run_gemini():
                    if system_instruction:
                        full_prompt = f"{system_instruction}\n\nUser Question: {prompt}"
                    else:
                        full_prompt = prompt
                    
                    response = self.gemini_model.generate_content(full_prompt)
                    return response.text

                return await asyncio.to_thread(run_gemini)
            except Exception as e:
                logger.error(f"Gemini failed: {e}. Falling back to Ollama.")
                print(f"Gemini Error: {e}")

        # 2. Try Ollama (Local Fallback)
        try:
            logger.info(f"Generating with Ollama ({self.ollama_model})...")
            
            def run_ollama():
                if system_instruction:
                    messages = [
                        {'role': 'system', 'content': system_instruction},
                        {'role': 'user', 'content': prompt}
                    ]
                    response = self.ollama_client.chat(model=self.ollama_model, messages=messages)
                    if hasattr(response, 'message'):
                        return response.message.content
                    return response['message']['content']
                else:
                    response = self.ollama_client.generate(model=self.ollama_model, prompt=prompt)
                    return response['response'] if isinstance(response, dict) else response.response

            return await asyncio.to_thread(run_ollama)
                
        except Exception as e:
            logger.error(f"All LLM providers failed: {e}")
            return f"I apologize, but I am currently unable to reach my AI brain. Please ensure either Gemini API is active or Ollama is running locally. (Error: {str(e)})"

# Singleton instance
llm_provider = LLMProvider()

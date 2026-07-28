import json
from google import genai
from app.core.config import settings

def get_ai_advice(question: str, context: dict = None) -> str:
    if not settings.GEMINI_API_KEY:
        return "AI features are currently disabled because the Gemini API Key is missing."
    
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    system_instruction = "You are a highly intelligent financial advisor for the RepayMaster AI platform. Provide concise, professional, and actionable loan advice. Format using markdown."
    
    prompt = f"User Question: {question}\n"
    if context:
        prompt += f"Context: {json.dumps(context)}\n"
        
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.7,
            )
        )
        return response.text
    except Exception as e:
        return f"Sorry, I encountered an error while analyzing your request: {str(e)}"

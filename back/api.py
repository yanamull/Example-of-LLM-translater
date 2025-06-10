import os
from typing import Optional
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pathlib import Path

# Путь к файлу .env (для исключения проблем с обнаружением файла)
env_path = Path("back/api_key.env").absolute()
load_dotenv(env_path)

api_service = FastAPI(
    docs_url="/docs",
    redoc_url=None,
    openapi_url="/openapi.json",
    default_response_class=JSONResponse,
)

api_service.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

TRANSLATION_MODEL = os.getenv("MODEL_NAME", "meta-llama/llama-4-maverick:free") # модель по умолчанию
OPENROUTER_ENDPOINT = os.getenv("API_URL", "https://openrouter.ai/api/v1/chat/completions")
AUTH_TOKEN = os.environ.get("API_KEY")

if not AUTH_TOKEN:
    raise RuntimeError("Authorization token is required")

# Модель Pydantic для входных данных перевода
class LanguageTranslation(BaseModel):
    content: str = Field(..., alias="text", description="Input text for translation")
    from_lang: str = Field(..., alias="source_language", description="Source language code")
    to_lang: str = Field(..., alias="target_language", description="Target language code")

# Модель Pydantic для результатов перевода
class TranslationResult(BaseModel):
    translation: str = Field(..., description="Translated text content")
    source: str = Field(..., description="Source language identifier")
    target: str = Field(..., description="Target language identifier")

# Асинхронная функция для запроса к LLM (Large Language Model)
async def fetch_llm_response(instruction: str, user_input: str) -> Optional[str]:
    """
    Отправляет запрос к LLM API и возвращает ответ.
    
    Args:
        instruction: Системное сообщение с инструкциями для модели
        user_input: Текст пользователя для обработки
    
    Returns:
        Ответ от модели или None в случае ошибки
    """

    request_headers = {
        "Authorization": f"Bearer {AUTH_TOKEN}",
        "Accept": "application/json",
    }
    
    request_body = {
        "model": TRANSLATION_MODEL,
        "messages": [
            {"role": "system", "content": instruction},
            {"role": "user", "content": user_input}
        ],
        "temperature": 0.7,
    }

# Создание асинхронного HTTP клиента с таймаутом 60 секунд
    async with httpx.AsyncClient(timeout=60.0) as http_client:
        try:
            llm_response = await http_client.post(
                OPENROUTER_ENDPOINT,
                headers=request_headers,
                json=request_body
            )
            llm_response.raise_for_status() # Проверка на ошибки HTTP
            response_data = llm_response.json() # Парсинг JSON ответа
            return response_data["choices"][0]["message"]["content"].strip('"\' \n') # Извлечение и очистка текста ответа
        
        except httpx.RequestError as request_error:
            # Ошибка при запросе (например, проблемы с сетью)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="LLM service unavailable"
            )
        
        except httpx.HTTPStatusError as http_error:
            # Ошибка HTTP (например, 404, 500 и т.д.)
            raise HTTPException(
                status_code=http_error.response.status_code,
                detail="Error processing translation request"
            )

@api_service.post(
    "/translate",
    response_model=TranslationResult,
    status_code=status.HTTP_200_OK,
    summary="Translate text between languages"
)
async def process_translation(translation_data: LanguageTranslation) -> TranslationResult:
    # формирование инструкции для промта модели
    system_message = (
        f"Translate this text from {translation_data.from_lang} to {translation_data.to_lang}. "
        f"Maintain original style, line breaks, emojis and punctuation.\n\n"
    )

    try:
        translated_content = await fetch_llm_response(
            instruction=system_message,
            user_input=translation_data.content
        )

        return TranslationResult(
            translation=translated_content,
            source=translation_data.from_lang,
            target=translation_data.to_lang
        )
    except Exception as error:
        # Обработка любых других ошибок
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Translation failed: {str(error)}"
        )

@api_service.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="Service health check"
)
async def service_health_check() -> dict:
    """Endpoint для проверки работоспособности сервиса"""
    return {
        "service": "language-translator",
        "status": "operational",
        "version": "1.0.0"
    }

# Функция для запуска сервиса
def initialize_service():
    import uvicorn # ASGI сервер
    uvicorn.run(
        api_service,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", 8000)),
        log_level="info"
    )

if __name__ == "__main__":
    initialize_service()
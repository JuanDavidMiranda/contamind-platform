from pydantic_settings import BaseSettings


class Settings(BaseSettings):

    APP_NAME: str = "ContaMind AI"

    VERSION: str = "1.0.0"

    DESCRIPTION: str = (
        "AI Platform for Accounting Automation"
    )


settings = Settings()
import uuid
from pydantic import BaseModel, EmailStr, ConfigDict, Field

class RegisterIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=128)
class LoginIn(BaseModel): email: EmailStr; password: str
class TokenOut(BaseModel): access_token: str; token_type: str = "bearer"
class UserOut(BaseModel): id: uuid.UUID; email: str; name: str; role: str; model_config = ConfigDict(from_attributes=True)
class WorkspaceIn(BaseModel): name: str = Field(min_length=1, max_length=120); description: str = Field(default="", max_length=2000)
class WorkspaceOut(BaseModel): id: uuid.UUID; name: str; description: str; created_at: object; model_config = ConfigDict(from_attributes=True)
class FileOut(BaseModel):
    id: uuid.UUID; workspace_id: uuid.UUID; filename: str; mime_type: str; size: int; sha256: str; status: str; is_public: bool = False; created_at: object
    model_config = ConfigDict(from_attributes=True)
class FilePageOut(BaseModel): items: list[FileOut]; page: int; limit: int; total: int
class FilePublicAccessIn(BaseModel): is_public: bool
class ApiKeyCreateIn(BaseModel): name: str = Field(min_length=1, max_length=120)
class ApiKeyOut(BaseModel): id: uuid.UUID; workspace_id: uuid.UUID; name: str; key_prefix: str; created_at: object; revoked_at: object | None = None; model_config = ConfigDict(from_attributes=True)
class ApiKeyCreatedOut(ApiKeyOut): key: str

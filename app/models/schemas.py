from pydantic import BaseModel, Field
from typing import Optional, List, Literal

class VerifyRequest(BaseModel):
    license_key: str = Field(..., pattern=r"^YS-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$", max_length=20)
    device_id: str = Field(..., min_length=8, max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$")
    product_id: str = Field(..., min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$")
    version: Literal["1.0", "2.0"] = "1.0"

class GenerateRequest(BaseModel):
    token: str
    seats: int = Field(1, ge=1, le=100)
    duration_days: int = Field(0, ge=0)
    contact: Optional[str] = ""
    order_id: Optional[str] = ""
    remark: Optional[str] = ""
    product_ids: List[str] = Field(..., min_length=1)
    is_trial: bool = False

class AdminRequest(BaseModel):
    token: str
    license_key: Optional[str] = None

class BanRequest(AdminRequest):
    action: Literal["ban", "unban"]

class ResetRequest(AdminRequest):
    pass

class AnnouncementRequest(BaseModel):
    token: str
    product_id: str = Field(..., min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$")
    message: str = Field(..., max_length=1000)
    anno_mode: Literal["once", "daily"] = "once"

class DeleteRequest(AdminRequest):
    pass

class RegisterProductRequest(BaseModel):
    token: str
    pid: str = Field(..., min_length=2, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(..., min_length=1, max_length=100)

class PurgeTrashRequest(AdminRequest):
    pass

class RenameProductRequest(BaseModel):
    token: str
    old_id: str
    new_id: str

class DeleteProductRequest(BaseModel):
    token: str
    product_id: str = Field(..., min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$")

class DisplayNameRequest(BaseModel):
    token: str
    product_id: str
    display_name: str

class UpdatePromoUrlRequest(BaseModel):
    token: str
    product_id: str = Field(..., min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$")
    promo_url: str = Field(..., max_length=512)
    default_trial_days: int = Field(7, ge=1, le=365)

class RequestTrialRequest(BaseModel):
    hardware_id: str = Field(..., min_length=8, max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$")
    product_id: str = Field(..., min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$")

class UpdateLicenseRequest(BaseModel):
    token: str
    license_key: str
    user_contact: Optional[str] = None
    remark: Optional[str] = None
    max_seats: Optional[int] = Field(None, ge=1, le=500)
    product_ids: Optional[List[str]] = Field(None, min_length=1)

# --- 脚本更新中心模型 ---
class ScriptUpdateCheck(BaseModel):
    script_id: str = Field(..., pattern=r"^[a-zA-Z0-9_-]+$")
    current_version: str

class ScriptRegisterRequest(BaseModel):
    script_id: str = Field(..., pattern=r"^[a-zA-Z0-9_-]+$")
    name: str
    latest_version: str
    url_primary: str
    url_fallback: str
    changelog: Optional[str] = ""
    min_reaper: Optional[str] = "6.0"

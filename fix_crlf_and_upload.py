with open('backend/api/emails.py', 'r') as f:
    content = f.read()

# Add field_validator to the top pydantic imports
import_line = "from pydantic import BaseModel, EmailStr, Field"
new_import_line = "from pydantic import BaseModel, EmailStr, Field, field_validator"
content = content.replace(import_line, new_import_line)


start_marker = "class SendEmailRequest(BaseModel):"
end_marker = "@router.post(\"/send\")"

start_idx = content.find(start_marker)
end_idx = content.find(end_marker)

replacement = (
    "class SendEmailRequest(BaseModel):\n"
    "    to: EmailStr\n"
    "    subject: str = Field(..., max_length=256, pattern=r\"^[^\\r\\n]*$\")\n"
    "    body: str\n"
    "    in_reply_to: str | None = None  # O3: email threading support\n"
    "    references: str | None = None\n\n"
    "    @field_validator(\"subject\", \"in_reply_to\", \"references\", \"to\", mode=\"before\")\n"
    "    @classmethod\n"
    "    def no_crlf_str(cls, v):\n"
    "        if isinstance(v, str) and (chr(10) in v or chr(13) in v):\n"
    "            raise ValueError(\"CR/LF characters are not allowed in email headers\")\n"
    "        return v\n\n"
)

new_content = content[:start_idx] + replacement + content[end_idx:]

old_upload = """        normalized_filename = upload.filename.lower().strip() if upload.filename else ""
        if not upload.filename or not (
            normalized_filename.endswith(".eml")
            or normalized_filename.endswith(".zip")
            or normalized_filename.endswith(".mbox")
        ):
            raise HTTPException(status_code=400, detail="invalid_file_type")"""

new_upload = """        normalized_filename = upload.filename.lower().strip() if upload.filename else ""
        if not upload.filename:
            raise HTTPException(status_code=400, detail="invalid_file_type")

        parts = normalized_filename.split(".")
        if len(parts) < 2:
            raise HTTPException(status_code=400, detail="invalid_file_type")

        valid_extensions = {".eml", ".zip", ".mbox"}
        ext = f".{parts[-1]}"
        if ext not in valid_extensions:
            raise HTTPException(status_code=400, detail="invalid_file_type")

        dangerous_exts = {".exe", ".sh", ".bat", ".cmd", ".vbs", ".ps1", ".js", ".scr"}
        for part in parts[1:]:
            if f".{part}" in dangerous_exts:
                raise HTTPException(status_code=400, detail="invalid_file_type")"""

new_content = new_content.replace(old_upload, new_upload)

with open('backend/api/emails.py', 'w') as f:
    f.write(new_content)

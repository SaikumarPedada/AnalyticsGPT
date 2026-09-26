from tortoise import fields
from tortoise.models import Model


class User(Model):
    user_id = fields.IntField(pk=True)
    username = fields.CharField(max_length=64, unique=True, index=True)
    email = fields.CharField(max_length=255, unique=True, index=True)
    password = fields.CharField(max_length=255)
    is_active = fields.BooleanField(default=True)
    last_login = fields.DatetimeField(null=True)
    last_session_ended = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "users"


class RefreshToken(Model):
    """Stored refresh tokens for rotation / revocation."""
    id = fields.IntField(pk=True)
    user = fields.ForeignKeyField("models.User", related_name="refresh_tokens", on_delete=fields.CASCADE, source_field="user_id")
    token_hash = fields.CharField(max_length=255, unique=True, index=True)
    expires_at = fields.DatetimeField()
    revoked = fields.BooleanField(default=False)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "refresh_tokens"


class ChatSession(Model):
    session_id = fields.CharField(pk=True, max_length=36)
    user = fields.ForeignKeyField("models.User", related_name="chat_sessions", on_delete=fields.CASCADE, source_field="user_id")
    title = fields.CharField(max_length=255, null=True)           # auto-generated from first message
    session_start = fields.DatetimeField(null=True)
    session_end = fields.DatetimeField(null=True)
    tokens_consumed = fields.IntField(default=0)
    tools_used = fields.TextField(default="[]")
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "chat_sessions"
        indexes = (
            ("user_id", "created_at"),
        )


class Message(Model):
    message_id = fields.IntField(pk=True)
    session = fields.ForeignKeyField("models.ChatSession", related_name="messages", on_delete=fields.CASCADE, source_field="session_id")
    user = fields.ForeignKeyField("models.User", related_name="messages", on_delete=fields.CASCADE, source_field="user_id")
    role = fields.CharField(max_length=16)       # "user" | "assistant" | "system"
    content = fields.TextField()
    tokens = fields.IntField(default=0)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "messages"
        indexes = (
            ("user_id", "created_at"),
            ("session_id", "created_at"),
        )


class Dataset(Model):
    dataset_id = fields.CharField(pk=True, max_length=36)
    filename = fields.CharField(max_length=255)
    content = fields.BinaryField()
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "datasets"

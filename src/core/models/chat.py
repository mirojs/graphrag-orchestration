"""Chat history models."""

from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field
import uuid


class ChatMessage(BaseModel):
    """Individual chat message."""
    
    role: str = Field(..., description="Message role (user, assistant, system)")
    content: str = Field(..., description="Message content")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_schema_extra = {
            "example": {
                "role": "user",
                "content": "What is the total amount in the invoice?",
                "timestamp": "2026-01-31T10:30:00Z"
            }
        }


class ChatSession(BaseModel):
    """Chat session with message history."""
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = Field(..., description="User ID (partition key)")
    conversation_id: str = Field(..., description="Conversation ID")
    messages: List[ChatMessage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Metadata
    partition_id: Optional[str] = Field(None, description="Group ID (B2B) or User ID (B2C)")
    route_preference: Optional[str] = Field(None, description="Preferred route (local, global, drift)")
    
    # Cosmos DB TTL (90 days)
    ttl: int = Field(default=7776000, description="Time to live in seconds")
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "user-456",
                "conversation_id": "conv-abc123",
                "messages": [
                    {"role": "user", "content": "What is the total?"},
                    {"role": "assistant", "content": "The total is $5,000."}
                ],
                "partition_id": "group-123"
            }
        }

from pydantic import BaseModel, Field
from langgraph.graph import MessagesState


class State(MessagesState):
    pass #TODO: define state
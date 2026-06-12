from pydantic import BaseModel, Field
from typing import List, Optional

class OBPAccountBalance(BaseModel):
    currency: str
    amount: str

class OBPAccount(BaseModel):
    id: str
    bank_id: str
    label: str
    number: str
    owners: List[str]
    type: str
    balance: OBPAccountBalance

class OBPTransactionDetails(BaseModel):
    type: str
    description: str
    posted: str
    completed: str
    new_balance: OBPAccountBalance
    value: OBPAccountBalance

class OBPTransaction(BaseModel):
    id: str
    this_account: OBPAccount
    details: OBPTransactionDetails

class OBPTransactionResponse(BaseModel):
    transactions: List[OBPTransaction]

class OBPAccountResponse(BaseModel):
    accounts: List[OBPAccount]

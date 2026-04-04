

from dataclasses import dataclass
from typing import Optional



@dataclass
class BotAction:
    kind: str
    amount: Optional[int] = None

    def __str__(self):
        if self.amount is None:
            return self.kind
        return f"{self.kind}:{self.amount}"
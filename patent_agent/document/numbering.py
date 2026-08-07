from dataclasses import dataclass


@dataclass
class NumberingRegistry:
    equations: int = 0
    figures: int = 0
    claims: int = 0

    def equation(self) -> int: self.equations += 1; return self.equations
    def figure(self) -> int: self.figures += 1; return self.figures
    def claim(self) -> int: self.claims += 1; return self.claims


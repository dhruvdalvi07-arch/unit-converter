#!/usr/bin/env python3
"""Advanced Universal Unit & Currency Conversion Suite."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple


# =====================================================================
# Terminal UI Utilities
# =====================================================================

class Style:
    _USE_COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ

    RESET = "\033[0m" if _USE_COLOR else ""
    BOLD = "\033[1m" if _USE_COLOR else ""
    DIM = "\033[2m" if _USE_COLOR else ""
    GREEN = "\033[92m" if _USE_COLOR else ""
    CYAN = "\033[96m" if _USE_COLOR else ""
    YELLOW = "\033[93m" if _USE_COLOR else ""
    RED = "\033[91m" if _USE_COLOR else ""


# =====================================================================
# Unit Models & Mathematical Engine
# =====================================================================

class UnitCategory(Enum):
    LENGTH = "Length"
    MASS = "Mass / Weight"
    TEMPERATURE = "Temperature"
    DATA = "Digital Storage"
    TIME = "Time"
    CURRENCY = "Foreign Exchange"


@dataclass
class UnitDefinition:
    symbol: str
    name: str
    aliases: List[str]
    # For linear conversions: to_base(val) = val * factor
    # For affine conversions (temperature): custom callables
    to_base: Callable[[float], float]
    from_base: Callable[[float], float]


class ConverterRegistry:
    """Manages multi-category conversion logic."""

    def __init__(self) -> None:
        self.categories: Dict[UnitCategory, Dict[str, UnitDefinition]] = {}
        self.alias_map: Dict[str, Tuple[UnitCategory, str]] = {}
        self._register_defaults()

    def add_unit(
        self,
        category: UnitCategory,
        symbol: str,
        name: str,
        factor_to_base: float,
        aliases: Optional[List[str]] = None,
    ) -> None:
        """Helper to register linear scaling units."""
        aliases = aliases or []
        unit_def = UnitDefinition(
            symbol=symbol,
            name=name,
            aliases=aliases,
            to_base=lambda val, f=factor_to_base: val * f,
            from_base=lambda val, f=factor_to_base: val / f,
        )
        self._store_unit(category, symbol, unit_def, aliases)

    def add_affine_unit(
        self,
        category: UnitCategory,
        symbol: str,
        name: str,
        to_base: Callable[[float], float],
        from_base: Callable[[float], float],
        aliases: Optional[List[str]] = None,
    ) -> None:
        """Helper to register non-linear units (e.g. Temperature)."""
        aliases = aliases or []
        unit_def = UnitDefinition(
            symbol=symbol,
            name=name,
            aliases=aliases,
            to_base=to_base,
            from_base=from_base,
        )
        self._store_unit(category, symbol, unit_def, aliases)

    def _store_unit(
        self,
        category: UnitCategory,
        symbol: str,
        unit_def: UnitDefinition,
        aliases: List[str],
    ) -> None:
        if category not in self.categories:
            self.categories[category] = {}

        norm_sym = symbol.lower()
        self.categories[category][norm_sym] = unit_def
        self.alias_map[norm_sym] = (category, norm_sym)

        for alias in aliases:
            self.alias_map[alias.lower()] = (category, norm_sym)

    def resolve_unit(self, token: str) -> Optional[Tuple[UnitCategory, UnitDefinition]]:
        key = token.strip().lower()
        if key in self.alias_map:
            cat, sym = self.alias_map[key]
            return cat, self.categories[cat][sym]
        return None

    def convert(self, value: float, from_unit_token: str, to_unit_token: str) -> Tuple[float, UnitDefinition, UnitDefinition]:
        res_from = self.resolve_unit(from_unit_token)
        res_to = self.resolve_unit(to_unit_token)

        if not res_from:
            raise ValueError(f"Unknown source unit: '{from_unit_token}'")
        if not res_to:
            raise ValueError(f"Unknown target unit: '{to_unit_token}'")

        cat_from, u_from = res_from
        cat_to, u_to = res_to

        if cat_from != cat_to:
            raise TypeError(
                f"Dimension mismatch: Cannot convert '{u_from.name}' ({cat_from.value}) "
                f"to '{u_to.name}' ({cat_to.value})."
            )

        # Value -> Base -> Destination
        base_val = u_from.to_base(value)
        final_val = u_to.from_base(base_val)

        return final_val, u_from, u_to

    def _register_defaults(self) -> None:
        # Base unit: Meter (m)
        self.add_unit(UnitCategory.LENGTH, "m", "Meters", 1.0, ["meter", "meters"])
        self.add_unit(UnitCategory.LENGTH, "km", "Kilometers", 1000.0, ["kilometer", "kilometre", "kms"])
        self.add_unit(UnitCategory.LENGTH, "cm", "Centimeters", 0.01, ["centimeter", "centimetre"])
        self.add_unit(UnitCategory.LENGTH, "mm", "Millimeters", 0.001, ["millimeter"])
        self.add_unit(UnitCategory.LENGTH, "mi", "Miles", 1609.344, ["mile", "miles"])
        self.add_unit(UnitCategory.LENGTH, "yd", "Yards", 0.9144, ["yard", "yards"])
        self.add_unit(UnitCategory.LENGTH, "ft", "Feet", 0.3048, ["foot", "feet"])
        self.add_unit(UnitCategory.LENGTH, "in", "Inches", 0.0254, ["inch", "inches"])
        self.add_unit(UnitCategory.LENGTH, "nmi", "Nautical Miles", 1852.0, ["nauticalmile"])

        # Base unit: Gram (g)
        self.add_unit(UnitCategory.MASS, "g", "Grams", 1.0, ["gram", "grams"])
        self.add_unit(UnitCategory.MASS, "kg", "Kilograms", 1000.0, ["kilogram", "kgs"])
        self.add_unit(UnitCategory.MASS, "mg", "Milligrams", 0.001, ["milligram"])
        self.add_unit(UnitCategory.MASS, "lb", "Pounds", 453.59237, ["lbs", "pound", "pounds"])
        self.add_unit(UnitCategory.MASS, "oz", "Ounces", 28.349523125, ["ounce", "ounces"])
        self.add_unit(UnitCategory.MASS, "t", "Metric Tonnes", 1_000_000.0, ["tonne", "tonnes"])

        # Base unit: Second (s)
        self.add_unit(UnitCategory.TIME, "s", "Seconds", 1.0, ["sec", "second", "seconds"])
        self.add_unit(UnitCategory.TIME, "ms", "Milliseconds", 0.001, ["millisecond"])
        self.add_unit(UnitCategory.TIME, "min", "Minutes", 60.0, ["minute", "minutes"])
        self.add_unit(UnitCategory.TIME, "hr", "Hours", 3600.0, ["hour", "hours", "h"])
        self.add_unit(UnitCategory.TIME, "d", "Days", 86400.0, ["day", "days"])
        self.add_unit(UnitCategory.TIME, "wk", "Weeks", 604800.0, ["week", "weeks"])

        # Base unit: Byte (B)
        self.add_unit(UnitCategory.DATA, "b", "Bits", 0.125, ["bit", "bits"])
        self.add_unit(UnitCategory.DATA, "B", "Bytes", 1.0, ["byte", "bytes"])
        self.add_unit(UnitCategory.DATA, "KB", "Kilobytes (Decimal)", 1_000.0, ["kilobyte"])
        self.add_unit(UnitCategory.DATA, "MB", "Megabytes (Decimal)", 1_000_000.0, ["megabyte"])
        self.add_unit(UnitCategory.DATA, "GB", "Gigabytes (Decimal)", 1_000_000_000.0, ["gigabyte"])
        self.add_unit(UnitCategory.DATA, "TB", "Terabytes (Decimal)", 1_000_000_000_000.0, ["terabyte"])
        self.add_unit(UnitCategory.DATA, "KiB", "Kibibytes (Binary)", 1024.0, ["kibibyte"])
        self.add_unit(UnitCategory.DATA, "MiB", "Mebibytes (Binary)", 1048576.0, ["mebibyte"])
        self.add_unit(UnitCategory.DATA, "GiB", "Gibibytes (Binary)", 1073741824.0, ["gibibyte"])

        # Base unit: Kelvin (K)
        self.add_affine_unit(
            UnitCategory.TEMPERATURE,
            "K",
            "Kelvin",
            to_base=lambda k: k,
            from_base=lambda k: k,
            aliases=["kelvin"],
        )
        self.add_affine_unit(
            UnitCategory.TEMPERATURE,
            "C",
            "Celsius",
            to_base=lambda c: c + 273.15,
            from_base=lambda k: k - 273.15,
            aliases=["celsius", "centigrade"],
        )
        self.add_affine_unit(
            UnitCategory.TEMPERATURE,
            "F",
            "Fahrenheit",
            to_base=lambda f: (f - 32.0) * (5.0 / 9.0) + 273.15,
            from_base=lambda k: (k - 273.15) * (9.0 / 5.0) + 32.0,
            aliases=["fahrenheit"],
        )


# =====================================================================
# Currency Exchange Subsystem (Live + Resilient Fallback)
# =====================================================================

class CurrencyEngine:
    """Handles Forex currency conversion with base currency USD."""

    # Baseline fallback rates relative to 1 USD
    FALLBACK_RATES: Dict[str, float] = {
        "usd": 1.0,
        "eur": 0.92,
        "gbp": 0.79,
        "inr": 83.5,
        "jpy": 154.2,
        "cad": 1.37,
        "aud": 1.52,
        "chf": 0.91,
        "cny": 7.24,
    }

    CURRENCY_NAMES: Dict[str, str] = {
        "usd": "US Dollar",
        "eur": "Euro",
        "gbp": "British Pound",
        "inr": "Indian Rupee",
        "jpy": "Japanese Yen",
        "cad": "Canadian Dollar",
        "aud": "Australian Dollar",
        "chf": "Swiss Franc",
        "cny": "Chinese Yuan",
    }

    def __init__(self, registry: ConverterRegistry) -> None:
        self.registry = registry
        self.rates = dict(self.FALLBACK_RATES)
        self.is_live = False
        self._fetch_live_rates()
        self._register_currencies()

    def _fetch_live_rates(self) -> None:
        """Attempts to sync with open exchange API; silently keeps fallbacks on failure."""
        url = "https://open.er-api.com/v6/latest/USD"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PythonUnitConverter/2.0"})
            with urllib.request.urlopen(req, timeout=2.5) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    if data.get("result") == "success":
                        raw_rates = data.get("rates", {})
                        for code, rate in raw_rates.items():
                            self.rates[code.lower()] = float(rate)
                        self.is_live = True
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, Exception):
            self.is_live = False

    def _register_currencies(self) -> None:
        # Base unit in registry: 1 USD
        for code, rate_per_usd in self.rates.items():
            name = self.CURRENCY_NAMES.get(code, code.upper())
            # to_base: amount in XYZ / rate = amount in USD
            # from_base: amount in USD * rate = amount in XYZ
            self.registry.add_affine_unit(
                UnitCategory.CURRENCY,
                code.upper(),
                name,
                to_base=lambda val, r=rate_per_usd: val / r,
                from_base=lambda usd, r=rate_per_usd: usd * r,
                aliases=[code.lower(), code.upper()],
            )


# =====================================================================
# CLI Driver & Natural Language Parser
# =====================================================================

class ConverterApp:
    def __init__(self) -> None:
        self.registry = ConverterRegistry()
        self.currency_engine = CurrencyEngine(self.registry)

    def run(self) -> None:
        self._print_header()
        while True:
            try:
                line = input(f"{Style.CYAN}convert ❯ {Style.RESET}").strip()
            except (KeyboardInterrupt, EOFError):
                print(f"\n{Style.YELLOW}Shutting down converter...{Style.RESET}")
                break

            if not line:
                continue

            low = line.lower()
            if low in ("exit", "quit", "q"):
                print(f"{Style.YELLOW}Goodbye!{Style.RESET}")
                break
            elif low in ("help", "?"):
                self._print_help()
            elif low in ("list", "units"):
                self._list_units()
            else:
                self._handle_query(line)

    def _handle_query(self, query: str) -> None:
        # Matches patterns like: "100 km to mi", "50.5 c in f", "12 usd -> inr"
        pattern = r"^([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*([a-zA-Z°]+)\s*(?:to|in|->|=)\s*([a-zA-Z°]+)$"
        match = re.match(pattern, query.strip())

        if not match:
            print(
                f"{Style.RED}Syntax error.{Style.RESET} Example usage: {Style.BOLD}100 km to mi{Style.RESET} "
                f"or {Style.BOLD}75 f to c{Style.RESET}. Type {Style.BOLD}help{Style.RESET} for details."
            )
            return

        val_str, u_from_str, u_to_str = match.groups()
        val = float(val_str)

        try:
            result, u_from, u_to = self.registry.convert(val, u_from_str, u_to_str)
            self._print_result(val, u_from, result, u_to)
        except (ValueError, TypeError) as err:
            print(f"{Style.RED}Error:{Style.RESET} {err}")

    def _print_result(self, val_in: float, u_in: UnitDefinition, val_out: float, u_out: UnitDefinition) -> None:
        # Decimal formatting to suppress scientific float artifacts when possible
        dec = Decimal(str(val_out))
        if abs(dec) < Decimal("0.000001") and dec != 0:
            formatted_out = f"{val_out:.6e}"
        else:
            formatted_out = f"{val_out:,.4f}".rstrip("0").rstrip(".")

        print(
            f"  {Style.GREEN}{Style.BOLD}{val_in:g} {u_in.symbol}{Style.RESET} ({u_in.name}) "
            f"= {Style.CYAN}{Style.BOLD}{formatted_out} {u_out.symbol}{Style.RESET} ({u_out.name})"
        )

    def _print_header(self) -> None:
        status = (
            f"{Style.GREEN}Live Online Sync Active{Style.RESET}"
            if self.currency_engine.is_live
            else f"{Style.YELLOW}Offline Mode (Fallback Reference Rates){Style.RESET}"
        )
        print(f"\n{Style.CYAN}{Style.BOLD}{'=' * 68}")
        print("          UNIVERSAL UNIT & CURRENCY CONVERSION ENGINE          ")
        print(f"{'=' * 68}{Style.RESET}")
        print(f"Fx Status: {status}")
        print(f"Quick Start: Type queries like '{Style.BOLD}100 km to mi{Style.RESET}' or '{Style.BOLD}150 USD to EUR{Style.RESET}'.")
        print(f"Commands: {Style.DIM}'list'{Style.RESET} (view units), {Style.DIM}'help'{Style.RESET}, {Style.DIM}'quit'{Style.RESET}\n")

    def _list_units(self) -> None:
        print(f"\n{Style.BOLD}Registered Conversion Domains:{Style.RESET}")
        for cat, units in self.registry.categories.items():
            syms = [f"{u.symbol} ({u.name})" for u in list(units.values())[:6]]
            more = f" +{len(units) - 6} more..." if len(units) > 6 else ""
            print(f"  {Style.CYAN}{cat.value:<18}{Style.RESET}: {', '.join(syms)}{more}")
        print()

    def _print_help(self) -> None:
        print(f"\n{Style.BOLD}Usage Instructions:{Style.RESET}")
        print("  Format:  <amount> <from_unit> [to|in|->] <to_unit>")
        print("  Examples:")
        print("    • 42.5 km to mi")
        print("    • 98.6 f in c")
        print("    • 1024 MiB -> GiB")
        print("    • 500 USD to INR")
        print("    • 12.5 kg to lb\n")


# =====================================================================
# Program Entrypoint
# =====================================================================

if __name__ == "__main__":
    app = ConverterApp()
    app.run()

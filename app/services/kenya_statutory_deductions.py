"""Kenyan statutory payroll deductions: PAYE, NSSF, SHIF and the Affordable Housing Levy.

Pure calculation, no database access. Rates are kept as dated schedules so a
payroll run for an earlier month uses the rates that applied then; adding a new
schedule is how a rate change is rolled out.

Order of calculation (Tax Laws (Amendment) Act, 2024, from December 2024):
NSSF, SHIF and the Housing Levy are deducted from pay before PAYE is worked out.

Rates must be confirmed against KRA, NSSF and SHA notices whenever a new
Finance Act or NSSF phase takes effect.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Tuple

CENT = Decimal('0.01')


@dataclass(frozen=True)
class StatutoryRates:
    version: str
    effective_from: date
    # Monthly PAYE bands as (upper limit of the band, rate); None is the top band.
    paye_bands: Tuple[Tuple[Decimal | None, Decimal], ...]
    personal_relief: Decimal
    nssf_rate: Decimal
    nssf_upper_earnings_limit: Decimal
    shif_rate: Decimal
    shif_minimum: Decimal
    housing_levy_rate: Decimal


_PAYE_BANDS = (
    (Decimal('24000'), Decimal('0.10')),
    (Decimal('32333'), Decimal('0.25')),
    (Decimal('500000'), Decimal('0.30')),
    (Decimal('800000'), Decimal('0.325')),
    (None, Decimal('0.35')),
)

SCHEDULES = (
    # NSSF Act 2013, phase 3.
    StatutoryRates(
        version='KE-2025-02',
        effective_from=date(2025, 2, 1),
        paye_bands=_PAYE_BANDS,
        personal_relief=Decimal('2400'),
        nssf_rate=Decimal('0.06'),
        nssf_upper_earnings_limit=Decimal('72000'),
        shif_rate=Decimal('0.0275'),
        shif_minimum=Decimal('300'),
        housing_levy_rate=Decimal('0.015'),
    ),
    # NSSF Act 2013, phase 4: upper earnings limit KES 108,000.
    StatutoryRates(
        version='KE-2026-02',
        effective_from=date(2026, 2, 1),
        paye_bands=_PAYE_BANDS,
        personal_relief=Decimal('2400'),
        nssf_rate=Decimal('0.06'),
        nssf_upper_earnings_limit=Decimal('108000'),
        shif_rate=Decimal('0.0275'),
        shif_minimum=Decimal('300'),
        housing_levy_rate=Decimal('0.015'),
    ),
)


@dataclass(frozen=True)
class StatutoryBreakdown:
    rates_version: str | None
    nssf_employee: Decimal
    nssf_employer: Decimal
    shif: Decimal
    housing_levy_employee: Decimal
    housing_levy_employer: Decimal
    taxable_pay: Decimal
    paye: Decimal

    @property
    def employee_total(self) -> Decimal:
        return self.nssf_employee + self.shif + self.housing_levy_employee + self.paye

    @property
    def employer_total(self) -> Decimal:
        return self.nssf_employer + self.housing_levy_employer


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


class KenyaStatutoryDeductions:
    @staticmethod
    def rates_for(period_start: date) -> StatutoryRates:
        applicable = [schedule for schedule in SCHEDULES if schedule.effective_from <= period_start]
        return applicable[-1] if applicable else SCHEDULES[0]

    @staticmethod
    def none(gross_pay: Decimal) -> StatutoryBreakdown:
        zero = Decimal('0.00')
        return StatutoryBreakdown(None, zero, zero, zero, zero, zero, _money(gross_pay), zero)

    @staticmethod
    def calculate(gross_pay: Decimal, period_start: date) -> StatutoryBreakdown:
        """Monthly deductions on pay earned in the period (after unpaid days)."""
        gross_pay = max(Decimal(gross_pay), Decimal('0'))
        if gross_pay == 0:
            return KenyaStatutoryDeductions.none(gross_pay)
        rates = KenyaStatutoryDeductions.rates_for(period_start)

        nssf = _money(min(gross_pay, rates.nssf_upper_earnings_limit) * rates.nssf_rate)
        shif = _money(max(gross_pay * rates.shif_rate, rates.shif_minimum))
        housing_levy = _money(gross_pay * rates.housing_levy_rate)
        taxable_pay = max(_money(gross_pay - nssf - shif - housing_levy), Decimal('0.00'))
        paye = KenyaStatutoryDeductions._paye(taxable_pay, rates)

        return StatutoryBreakdown(
            rates_version=rates.version,
            nssf_employee=nssf,
            nssf_employer=nssf,
            shif=shif,
            housing_levy_employee=housing_levy,
            housing_levy_employer=housing_levy,
            taxable_pay=taxable_pay,
            paye=paye,
        )

    @staticmethod
    def _paye(taxable_pay: Decimal, rates: StatutoryRates) -> Decimal:
        tax = Decimal('0')
        lower = Decimal('0')
        for upper, rate in rates.paye_bands:
            if taxable_pay <= lower:
                break
            band_top = taxable_pay if upper is None else min(taxable_pay, upper)
            tax += (band_top - lower) * rate
            if upper is None:
                break
            lower = upper
        return max(_money(tax - rates.personal_relief), Decimal('0.00'))

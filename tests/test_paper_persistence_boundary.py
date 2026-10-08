"""Persisted paper balances stay Decimal across entry and process restart."""
import json
import subprocess
import sys
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

import pytest

from krellbot.pack.model import Candle
from krellbot.venues.base import PairRules
from krellbot.venues.paper import PaperVenue


def rules(_pair):
    return PairRules(ordermin=Decimal('5'), costmin=Decimal('0.5'), lot_decimals=5, price_decimals=4)


def candle(ts=0, price='10'):
    return Candle(ts_ms=ts, open=Decimal(price), high=Decimal(price), low=Decimal(price),
                  close=Decimal(price), volume=Decimal('100'))


@pytest.mark.parametrize('action', ['exit', 'stop'])
def test_reconstruct_entry_owned_qty_then_new_interpreter_accounting(tmp_path: Path, action: str):
    PaperVenue('kraken', rules_provider=rules, candle_reader=lambda *_: [candle()],
               home=tmp_path, starting_cash=Decimal('1000'))
    venue = PaperVenue('kraken', rules_provider=rules, candle_reader=lambda *_: [candle()], home=tmp_path)
    venue.place_entry_with_stop('entry', Decimal('5'), Decimal('8'), pair='SUIUSD')
    assert isinstance(venue.owned_qty('SUIUSD'), Decimal)
    assert venue.owned_qty('SUIUSD') == Decimal('5')
    assert venue.balances() == {'USD': Decimal('949.7749'), 'SUI': Decimal('5')}
    code = """
import json, sys
from pathlib import Path
from decimal import Decimal
from tests.test_paper_persistence_boundary import rules, candle
from krellbot.venues.paper import PaperVenue
v = PaperVenue('kraken', rules_provider=rules, candle_reader=lambda *_: [candle(3600000, '7')], home=Path(sys.argv[1]))
assert isinstance(v.owned_qty('SUIUSD'), Decimal)
assert v.owned_qty('SUIUSD') == Decimal('5')
if sys.argv[2] == 'exit':
    v.place_exit('exit', v.owned_qty('SUIUSD'), pair='SUIUSD')
else:
    v.snapshot()
assert v.owned_qty('SUIUSD') == Decimal('0')
assert v.resting_stop('SUIUSD') is None
print(json.dumps({'balances': v.balances(), 'fills': [str(f.price) for f in v.snapshot().recent_fills]}, default=str))
"""
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path), action],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    sell = Decimal('7') * Decimal('0.9995')
    fee = (Decimal('5') * sell * Decimal('0.004')).quantize(Decimal('0.0001'), rounding=ROUND_DOWN)
    assert {k: Decimal(v) for k, v in body['balances'].items()} == {
        'USD': Decimal('949.7749') + Decimal('5') * sell - fee, 'SUI': Decimal('0')}
    assert [Decimal(p) for p in body['fills']] == [Decimal('10.0050'), sell]
    reconstructed = PaperVenue('kraken', rules_provider=rules, candle_reader=lambda *_: [], home=tmp_path)
    assert isinstance(reconstructed.owned_qty('SUIUSD'), Decimal)
    assert reconstructed.owned_qty('SUIUSD') == Decimal('0')
    assert reconstructed.balances()['USD'] == Decimal(body['balances']['USD'])

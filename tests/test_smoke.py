"""
スモークテスト: 全モジュールimport + 20人×120ターン完走

「歩く骨格」の完走を確認する。StubAgentは常にpass（退出条件が揃えば退出）
のため、実際には誰も対戦せず、全員がT120時間切れで脱落するのが正しい挙動。
"""

from engine.config import GameConfig
from engine.events import EventLogger
from engine.game import Game
from engine.negotiation import StubAgent


def test_all_engine_modules_import():
    import engine.cards  # noqa
    import engine.config  # noqa
    import engine.contracts  # noqa
    import engine.elimination  # noqa
    import engine.events  # noqa
    import engine.exit_rules  # noqa
    import engine.finance  # noqa
    import engine.game  # noqa
    import engine.judge  # noqa
    import engine.matches  # noqa
    import engine.models  # noqa
    import engine.negotiation  # noqa
    import engine.player  # noqa
    import engine.rng  # noqa
    import engine.trades  # noqa


def test_20_players_120_turns_completes():
    config = GameConfig.default_20()
    agents = {f"P{i:02d}": StubAgent() for i in range(1, config.num_players + 1)}
    logger = EventLogger(fixed_timestamp="2026-01-01T00:00:00+00:00")
    game = Game(config, agents, seed=42, logger=logger)
    result = game.run()

    # StubAgentは対戦しないため、誰も生還条件（カード0枚）を満たさない
    assert result["survivors"] == []
    assert len(result["eliminated"]) == 20
    assert all(v == "TIMEOUT" for v in result["eliminated"].values())

    # 全員が最終的にis_alive=False（対戦していないので有意な資産変動はない）
    for p in game.players.values():
        assert p.is_alive is False
        assert p.stars == 0  # 時間切れ清算で没収済み

    assert any(e.event_type == "GAME_START" for e in logger.events)
    assert any(e.event_type == "GAME_END" for e in logger.events)
    assert sum(1 for e in logger.events if e.event_type == "TIMEOUT") == 20
    # interest_interval_turns=10、total_turns=120で12回のはず
    assert sum(1 for e in logger.events if e.event_type == "INTEREST") == 12 * 20


def test_deterministic_with_same_seed():
    config = GameConfig.dev_small(num_players=6, total_turns=30)

    def run(seed: int) -> dict:
        agents = {f"P{i:02d}": StubAgent() for i in range(1, config.num_players + 1)}
        logger = EventLogger(fixed_timestamp="t")
        game = Game(config, agents, seed=seed, logger=logger)
        return game.run()

    r1 = run(seed=7)
    r2 = run(seed=7)
    assert r1 == r2


def test_save_jsonl_roundtrip(tmp_path):
    config = GameConfig.dev_small(num_players=4, total_turns=15)
    agents = {f"P{i:02d}": StubAgent() for i in range(1, config.num_players + 1)}
    logger = EventLogger(fixed_timestamp="t")
    game = Game(config, agents, seed=1, logger=logger)
    game.run()
    out = tmp_path / "events.jsonl"
    logger.save_jsonl(out)
    lines = out.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == len(logger.events)
    import json
    first = json.loads(lines[0])
    assert first["event_type"] == "GAME_START"

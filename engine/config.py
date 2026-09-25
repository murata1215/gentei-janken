"""
経済パラメータ設定モジュール

ゲーム全体の経済パラメータを管理する。仕様書§11の確定パラメータ一覧に対応。
§12.1 の未決事項は「両案を config フラグとして持つ」形で表現し、値の変更のみで
挙動を切り替えられるようにする（rules/project.md「設定の単一ソース化ルール」）。
"""

from pydantic import BaseModel


class GameConfig(BaseModel):
    """
    ゲーム経済パラメータの設定クラス

    全パラメータはコンストラクタ引数で上書き可能。
    default_20() / dev_small() クラスメソッドで標準設定を取得できる。
    スクリプト側で個別に GameConfig(...) を組み立てて設定を再現するのは禁止
    （rules/project.md 参照）。プリセット関数を必ず経由すること。
    """

    # --- 基本構成（§11） ---
    num_players: int = 20
    """プレイヤー数（§11: 20）"""

    total_turns: int = 120
    """ターン数（§11: 120。原作の4時間に相当）"""

    cards_per_hand: tuple[int, int, int] = (4, 4, 4)
    """初期手札構成（グー・チョキ・パーの順、§2.1: 各4枚計12枚）"""

    initial_stars: int = 3
    """初期★（§2.1/§3.2: 1人3個。場全体で num_players * initial_stars 個に固定）"""

    survival_stars_min: int = 3
    """生還に必要な★の最低数（§1.1/§6.1: 3個以上）"""

    # --- 借入・利息（§2） ---
    loan_min: int = 1_000_000
    """借入最低額（§2.1/§11: 100万円）"""

    loan_max: int = 10_000_000
    """借入最大額（§2.1/§11: 1000万円）"""

    interest_rate: float = 0.015
    """利率（§2.3: 1.5%複利）"""

    interest_interval_turns: int = 10
    """
    利息の計上間隔（§2.3/§12.1 未決事項）。
    初期値10ターンごと（計12回）。原作寄りの5ターンごと（計24回）案あり。
    §12.2 Botシミュレーションの結果を見てから値の変更だけで切り替える。
    """

    repay_unlock_turn: int = 0
    """
    §9.3 案2（未決事項）: 序盤の任意返済を禁止するターン数。
    0（既定）なら T1 から任意返済可能（仕様書どおり）。
    Nを設定するとターンN以前は repay アクションが不成立になる想定
    （抜け穴対策。engine/finance.py で参照）。
    """

    survival_cash_min: int = 0
    """
    §9.3 案1（未決事項）: 生還に必要な清算後現金の下限。
    0（既定）なら現金ラインなし（仕様書どおり、全員あいこ抜け穴が残る）。
    正の値を設定すると exit_rules.py の退出条件に追加される。
    """

    # --- 公開/秘匿の範囲（§12.1 未決事項） ---
    reveal_hands_publicly: bool = False
    """True: 対戦で出した手を全員に公開する。既定False（当事者だけが知る、§8.2）"""

    reveal_hand_count: bool = False
    """True: 各プレイヤーの手札枚数を公開する。既定False（秘匿、§8.2）"""

    # --- 対戦（§4） ---
    match_fee: int = 0
    """対戦料（§4: かからない。将来の拡張用に残す）"""

    offer_ttl_turns: int = 1
    """申込の有効期間（§4.3/§11: 翌ターン終わりまで）"""

    matches_per_turn: int = 1
    """1人が1ターンに行える対戦数の上限（§4.3/§11: 1回まで）"""

    # --- ★買い取り（§6.2） ---
    surplus_star_buyback: int = 1_000_000
    """余剰★の買取額（§6.2/§9.1/§11: 1個100万円。3個を超える分のみ）"""

    # --- 正式契約（§7.2） ---
    contract_fee: int = 100_000
    """契約発行料（§7.2/§11: 10万円、提案者負担）"""

    # --- 匿名通信（§7.5） ---
    anonymous_message_fee: int = 100_000
    """匿名通信費（§7.5/§11: 10万円）"""

    anonymous_message_limit_per_turn: int = 1
    """匿名通信の1ターン1人あたり上限（§7.5/§11: 1通まで）"""

    @classmethod
    def default_20(cls) -> "GameConfig":
        """20人版デフォルト設定を返す（仕様書§11の確定パラメータに準拠）"""
        return cls()

    @classmethod
    def dev_small(cls, num_players: int = 4, total_turns: int = 20) -> "GameConfig":
        """
        開発・スモークテスト用の小規模設定を返す

        人数とターン数を縮小するだけで、他の経済パラメータは default_20() と同一
        （rules/project.md の単一ソース原則: 個別に値を再定義しない）。
        """
        return cls(num_players=num_players, total_turns=total_turns)

"""
嘘八百万 —限定ジャンケン— ドメインモデル

仕様書 v0.1（`doc/spec/gentei_janken_v0_1.md`）の型定義を提供する。
本ファイルは正本ではなく仕様書が正本。ここは仕様書の型への写像。
"""

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


# =============================================================================
# 手・カード（§3.1）
# =============================================================================

class Hand(str, Enum):
    """ジャンケンの手（§3.1: グー・チョキ・パー各4枚）"""
    ROCK = "ROCK"
    SCISSORS = "SCISSORS"
    PAPER = "PAPER"


class Card(BaseModel):
    """
    1枚のカード（§3.1）

    手の種類のみを持つ。card_id はプレイヤー内で一意（トレードで受け取った
    カードが衝突する場合は dangou-card の swap_card と同様にサフィックスを
    付けてリネームする想定。card.py の create_deck() 参照）。
    """
    hand: Hand
    card_id: str


# =============================================================================
# プレイヤー状態
# =============================================================================

EliminationType = Literal["FORCED_EXIT", "CONTRACT_VIOLATION", "TIMEOUT"]
"""脱落の種別（§1.2）: 強制退場 / 契約違反 / 時間切れ"""


class PlayerState(BaseModel):
    """
    1プレイヤーの状態

    現金・借金残高は秘匿（§8.2）。★の数・初期借入額は公開情報。
    """
    player_id: str
    cards: list[Card] = Field(default_factory=list)
    """未使用の手札（予約中のカードも含む。§5.3の個別通知参照）"""

    reserved_card_ids: list[str] = Field(default_factory=list)
    """
    対戦申込・受諾で封をして提出中のカードのcard_id集合（§4.1）。予約中は他の用途に使えない。
    リストにしているのは「自分が出している申込（未受諾）」と「相手の申込を受諾した対戦
    （同ターン内に開示され即座に解放される）」が同時に成立しうるため（§4.3は自分が
    "出せる"申込を1件までに制限するのみで、"受け取る"申込の数に上限はない）。
    """

    stars: int = 3
    """★の数（§3.2: 公開情報）"""

    cash: int = 0
    """現金（秘匿）"""

    debt: int = 0
    """借金残高（秘匿。利息を含む）"""

    initial_loan: int = 0
    """開始時の借入額（§2.2: 公開情報。以後の借入は不可）"""

    is_alive: bool = True
    """場に残っているか（強制退場・時間切れでFalseになる）"""

    has_exited: bool = False
    """退出済みか（§6: 生還者）。is_aliveとは独立（退出者はis_alive=Falseだが脱落ではない）"""

    exit_turn: int | None = None
    """退出したターン番号（未退出ならNone）"""

    final_assets: int | None = None
    """清算後の最終資産（§6.2）。試合終了まで秘匿（§8.2）"""

    elimination_type: EliminationType | None = None
    """脱落種別（§1.2）。脱落していなければNone"""

    elimination_turn: int | None = None
    """脱落が確定したターン番号"""


# =============================================================================
# 対戦（§4）
# =============================================================================

MatchOfferStatus = Literal["pending", "accepted", "resolved", "expired", "withdrawn", "declined"]


class MatchOffer(BaseModel):
    """
    対戦の申込〜開示（§4.1）

    申込時に challenger_hand/challenger_card_id を封じて提出する。
    受諾時に opponent_hand/opponent_card_id が埋まり、そのターンの終わりに
    同時開示（judge.judge()）して MatchResult を生成する。
    """
    offer_id: str
    challenger_id: str
    opponent_id: str
    turn_offered: int
    challenger_hand: Hand
    challenger_card_id: str
    status: MatchOfferStatus = "pending"
    opponent_hand: Hand | None = None
    opponent_card_id: str | None = None
    turn_resolved: int | None = None


MatchOutcome = Literal["challenger_win", "opponent_win", "draw"]


class MatchResult(BaseModel):
    """対戦の開示結果（§4.2）"""
    offer_id: str
    challenger_id: str
    opponent_id: str
    challenger_hand: Hand
    opponent_hand: Hand
    outcome: MatchOutcome
    turn: int


# =============================================================================
# 即時取引（§7.1）
# =============================================================================

class AssetOffer(BaseModel):
    """一方が差し出す資産束（カード・★・現金の任意組み合わせ、§7.1）"""
    card_ids: list[str] = Field(default_factory=list)
    stars: int = 0
    cash: int = 0


TradeStatus = Literal["pending", "accepted", "expired", "withdrawn"]


class TradeProposal(BaseModel):
    """即時取引の提案（§7.1）。提案翌ターンの終わりまでに受諾されなければ失効する"""
    trade_id: str
    proposer_id: str
    target_id: str
    turn_proposed: int
    give: AssetOffer
    """proposer → target へ渡す資産"""
    receive: AssetOffer
    """target → proposer へ渡す資産"""
    status: TradeStatus = "pending"


# =============================================================================
# 正式契約（§7.2〜§7.4）
# =============================================================================

class ObligationType(str, Enum):
    """契約の型（§7.2）"""
    TYPE_A = "TYPE_A"  # 指定ターンの金銭支払い
    TYPE_B = "TYPE_B"  # 行動の指定（§7.3）
    TYPE_C = "TYPE_C"  # 条件付き金銭支払い（§7.4）
    TYPE_D = "TYPE_D"  # 指定ターンのカードまたは★の引き渡し（新設）


ObligationStatus = Literal["pending", "fulfilled", "violated", "expired"]


class Obligation(BaseModel):
    """契約1件が課す義務。義務単位で履行・失効を管理する（§6.3参照）"""
    obligation_id: str
    obligor_id: str
    """義務者"""
    obligation_type: ObligationType
    details: dict[str, Any] = Field(default_factory=dict)
    """型ごとの詳細（型Aは金額とターン、型Bは§7.3の3種、型Cは§7.4の条件、型Dはカード/★とターン）"""
    status: ObligationStatus = "pending"


ContractStatus = Literal["pending", "active", "fulfilled", "violated", "cancelled"]


class Contract(BaseModel):
    """正式契約（§7.2）。発行料10万円は提案者負担。存在と当事者名は公示、内容は当事者のみ"""
    contract_id: str
    proposer_id: str
    party_ids: list[str]
    obligations: list[Obligation] = Field(default_factory=list)
    status: ContractStatus = "pending"
    turn_created: int


# =============================================================================
# 公開報奨（§7.5）
# =============================================================================

BountyStatus = Literal["open", "claimed", "expired", "cancelled"]


class Bounty(BaseModel):
    """公開報奨（§7.5。v0.5 §7.2 を流用、条件は§7.4と同じ事実に置き換え）"""
    bounty_id: str
    poster_id: str | None
    """匿名の場合はNone（掲載者は秘匿）"""
    condition: dict[str, Any]
    reward: int
    status: BountyStatus = "open"
    turn_posted: int


# =============================================================================
# アクション（§5.2）
# =============================================================================

class DmAction(BaseModel):
    type: Literal["dm"] = "dm"
    player_id: str
    to: str
    message: str


class BroadcastAction(BaseModel):
    type: Literal["broadcast"] = "broadcast"
    player_id: str
    message: str


class AnonymousBroadcastAction(BaseModel):
    """匿名通信（§7.5: 10万円で1メッセージ、1ターン1通まで）"""
    type: Literal["anonymous_broadcast"] = "anonymous_broadcast"
    player_id: str
    message: str


class TransferAction(BaseModel):
    type: Literal["transfer"] = "transfer"
    player_id: str
    to: str
    amount: int


class RepayAction(BaseModel):
    """任意返済（§2.4: いつでも可能）"""
    type: Literal["repay"] = "repay"
    player_id: str
    amount: int


class MatchOfferAction(BaseModel):
    """対戦の申込（§4.1 ステップ1）"""
    type: Literal["match_offer"] = "match_offer"
    player_id: str
    opponent_id: str
    hand: Hand
    card_id: str


class MatchAcceptAction(BaseModel):
    """対戦の受諾（§4.1 ステップ2）"""
    type: Literal["match_accept"] = "match_accept"
    player_id: str
    offer_id: str
    hand: Hand
    card_id: str


class MatchDeclineAction(BaseModel):
    type: Literal["match_decline"] = "match_decline"
    player_id: str
    offer_id: str


class MatchWithdrawAction(BaseModel):
    """申込者による取り下げ（§4.3: 受諾前なら可能）"""
    type: Literal["match_withdraw"] = "match_withdraw"
    player_id: str
    offer_id: str


class TradeProposeAction(BaseModel):
    type: Literal["trade_propose"] = "trade_propose"
    player_id: str
    target_id: str
    give: AssetOffer
    receive: AssetOffer


class TradeAcceptAction(BaseModel):
    type: Literal["trade_accept"] = "trade_accept"
    player_id: str
    trade_id: str


class TradeRejectAction(BaseModel):
    type: Literal["trade_reject"] = "trade_reject"
    player_id: str
    trade_id: str


class TradeWithdrawAction(BaseModel):
    type: Literal["trade_withdraw"] = "trade_withdraw"
    player_id: str
    trade_id: str


class ContractProposeAction(BaseModel):
    """正式契約の提案（§7.2）。obligationsは正規化前の生データ（contracts.py入口で正規化）"""
    type: Literal["contract_propose"] = "contract_propose"
    player_id: str
    party_ids: list[str]
    obligations: list[dict[str, Any]]


class ContractSignAction(BaseModel):
    type: Literal["contract_sign"] = "contract_sign"
    player_id: str
    contract_id: str


class ContractCancelAction(BaseModel):
    """全当事者合意による契約解除"""
    type: Literal["contract_cancel"] = "contract_cancel"
    player_id: str
    contract_id: str


class BountyPostAction(BaseModel):
    type: Literal["bounty_post"] = "bounty_post"
    player_id: str
    condition: dict[str, Any]
    reward: int
    anonymous: bool = False


class BountyCancelAction(BaseModel):
    type: Literal["bounty_cancel"] = "bounty_cancel"
    player_id: str
    bounty_id: str


class ExitAction(BaseModel):
    """退出（§6.1）。条件を満たさない場合は不成立（脱落しない）"""
    type: Literal["exit"] = "exit"
    player_id: str


class WaitAction(BaseModel):
    """
    待機（§5.2）: 「T45まで待つ」または「DM・対戦申込・取引提案が届いたら起こして」。
    待機中はLLMを呼ばずにターンを飛ばす。
    """
    type: Literal["wait"] = "wait"
    player_id: str
    until_turn: int | None = None
    wake_on_event: bool = False


class PassAction(BaseModel):
    type: Literal["pass"] = "pass"
    player_id: str


Action = Annotated[
    DmAction | BroadcastAction | AnonymousBroadcastAction |
    TransferAction | RepayAction |
    MatchOfferAction | MatchAcceptAction | MatchDeclineAction | MatchWithdrawAction |
    TradeProposeAction | TradeAcceptAction | TradeRejectAction | TradeWithdrawAction |
    ContractProposeAction | ContractSignAction | ContractCancelAction |
    BountyPostAction | BountyCancelAction |
    ExitAction | WaitAction | PassAction,
    Field(discriminator="type"),
]


# =============================================================================
# イベント（ログ用）
# =============================================================================

class GameEvent(BaseModel):
    """
    ゲームイベント（JSONL出力用）

    全ゲームイベントを時系列で記録する。dangou-card の GameEvent と同一構造
    （engine/events.py が本クラスに依存する）。
    """
    event_type: str
    """イベント種別（例: GAME_START, MATCH_RESOLVED, FORCED_EXIT等）"""

    timestamp: str
    """ISO8601形式のタイムスタンプ"""

    round_num: int
    """本作ではターン番号を格納する（dangou-cardのround_numと同じフィールド名を流用）"""

    phase: str
    """ターン処理ステップ名（§5.1: notice/collect/resolve/reveal/contracts/eliminate/finance/exit）"""

    step: int | None = None
    """ターン処理内のStep番号（§5.1: 1-8、未使用ならNone）"""

    data: dict[str, Any] = Field(default_factory=dict)
    """イベント固有データ"""

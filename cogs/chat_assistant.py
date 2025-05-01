import logging
import traceback
import discord
from discord.ext import commands, tasks
from core.config import settings
from openai import OpenAI
from datetime import datetime
from db.session import SessionLocal
from queries.channel_query import select_chatbot_channel
from typing import List, Dict, Any, Optional

# 로거 설정
logger = logging.getLogger("cogs.chat_assistant")

key=settings.OPENAI_API_KEY


class NonsenseChatbot(commands.Cog):
    """
    헛소리봇 - 채널의 대화 맥락을 기반으로 엉뚱하고 재미있는 답변을 제공하는 Discord 챗봇
    
    특징:
    - 채널의 최근 대화 맥락을 이해해 관련 있는 헛소리 생성
    - 5분 이상 대화가 없으면 자동으로 헛소리 발생
    """
    def __init__(self, bot):
        self.bot = bot
        self.client = OpenAI(
            api_key=key,
            base_url="https://api.deepseek.com/v1"
        )

        # Discord 메시지 길이 제한
        self.MAX_DISCORD_LENGTH = 2000
        self.DEFAULT_MAX_TOKENS = 1000
        
        # 메시지 캐시 (채널별로 최근 대화 저장)
        self.message_history = {}
        self.MAX_HISTORY = 30  # 30개 메시지로 확장
        
        # 채널별 마지막 메시지 시간 추적
        self.last_message_time = {}
        self.INACTIVE_THRESHOLD = 5 * 60  # 5분 (초 단위)
        
        # 채널 목록 캐시
        self.chatbot_channels = {}
        
        # 비활성 채널 감지 백그라운드 작업 시작
        self.check_inactive_channels.start()
    
    def cog_unload(self):
        """코그가 언로드될 때 호출되는 메서드"""
        self.check_inactive_channels.cancel()
    
    async def load_chatbot_channels(self):
        """DB에서 봇 채널 목록 로드"""
        try:
            with SessionLocal() as db:
                # 모든 서버에서 채팅 봇 채널 조회 (모든 길드 가져오기)
                for guild in self.bot.guilds:
                    guild_id = str(guild.id)
                    # 채널 번호 조회
                    chatbot_channel_id = select_chatbot_channel(db, guild_id)
                    if chatbot_channel_id:
                        self.chatbot_channels[guild_id] = str(chatbot_channel_id)
                
                logger.info(f"chatbot 채널 {len(self.chatbot_channels)}개 로드됨")
        except Exception as e:
            logger.error(f"봇 채널 로드 중 오류: {e}")
            logger.error(traceback.format_exc())
    
    @tasks.loop(seconds=30)  # 30초마다 확인
    async def check_inactive_channels(self):
        """일정 시간 동안 비활성 상태인 채널 감지"""
        try:
            # 봇이 준비되지 않았으면 스킵
            if not self.bot.is_ready():
                return
                
            # 채널 목록 로드 (처음 실행 시)
            if not self.chatbot_channels:
                await self.load_chatbot_channels()
                
            current_time = datetime.now()
            channels_to_check = []
            
            # 활성 채널 목록 구성
            for guild_id, channel_id in self.chatbot_channels.items():
                try:
                    channel = self.bot.get_channel(int(channel_id))
                    if channel:
                        channels_to_check.append(channel)
                except Exception as e:
                    logger.error(f"채널 {channel_id} 가져오기 실패: {e}")
            
            # 각 채널 확인
            for channel in channels_to_check:
                channel_id = str(channel.id)
                
                # 채널에 메시지 이력이 있고, 마지막 메시지 시간이 기록되어 있는 경우
                if channel_id in self.last_message_time:
                    last_time = self.last_message_time[channel_id]
                    elapsed_seconds = (current_time - last_time).total_seconds()
                    
                    # 5분 이상 비활성 상태
                    if elapsed_seconds >= self.INACTIVE_THRESHOLD:
                        logger.info(f"채널 {channel.name} ({channel_id}) 비활성 감지: {elapsed_seconds:.0f}초 경과")
                        
                        # 히스토리 가져오기
                        history = self.get_channel_history(channel_id)
                        
                        # 히스토리가 충분히 있는 경우에만 자동 헛소리
                        if len(history) >= 3:  # 최소 3개 메시지가 있어야 맥락 파악 가능
                            # 마지막 메시지가 봇이 아닌 경우에만 자동 헛소리
                            if not self.is_last_message_from_bot(channel_id):
                                # 자동 헛소리 생성 및 전송
                                await self.send_random_nonsense(channel, history)
                                
                                # 마지막 메시지 시간 업데이트
                                self.last_message_time[channel_id] = current_time
        except Exception as e:
            logger.error(f"비활성 채널 확인 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
    
    def is_last_message_from_bot(self, channel_id):
        """채널의 마지막 메시지가 봇에서 온 것인지 확인"""
        channel_id = str(channel_id)
        history = self.message_history.get(channel_id, [])
        
        if not history:
            return False
            
        # 채널 이력에서 마지막 메시지의 작성자가 "[헛소리봇]"으로 시작하는지 확인
        last_msg = history[-1]
        return "[헛소리봇]" in last_msg.get("content", "")
    
    @check_inactive_channels.before_loop
    async def before_check_inactive_channels(self):
        """봇이 준비될 때까지 대기"""
        await self.bot.wait_until_ready()
        logger.info("비활성 채널 감지 루프 시작됨")
    
    async def send_random_nonsense(self, channel, history):
        """자동 헛소리 생성 및 전송"""
        try:
            # 채널에 타이핑 시작
            async with channel.typing():
                # 자동 헛소리 생성
                nonsense = await self.generate_nonsense("", history, is_auto=True)
                
                if nonsense:
                    # [헛소리봇] 접두어 추가
                    # formatted_message = f"[헛소리봇] {nonsense}"
                    
                    # 메시지 전송 (답장이 아닌 새 메시지로)
                    await channel.send(nonsense)
                    logger.info(f"비활성 채널 {channel.name}에 자동 헛소리 전송 (길이: {len(nonsense)}자)")
        except Exception as e:
            logger.error(f"자동 헛소리 전송 중 오류: {e}")
    
    @commands.Cog.listener()
    async def on_message(self, message):
        """
        Discord 채널의 메시지를 감지하여 처리합니다.
        """
        # 봇 메시지는 무시
        if message.author.bot:
            return
        
        # 마지막 메시지 시간 업데이트
        channel_id = str(message.channel.id)
        self.last_message_time[channel_id] = datetime.now()
        
        # 메시지 히스토리에 추가
        self.add_to_history(message)
            
        # 봇이 언급되었거나 "동글" 키워드가 있는 경우에만 응답
        if self.bot.user.mentioned_in(message) or "동글" in message.content.lower():
            async with message.channel.typing():
                # 채널 히스토리 가져오기
                history = self.get_channel_history(message.channel.id)
                
                # 헛소리 응답 생성
                response = await self.generate_nonsense(message.content, history)
                
                if response:
                    # [헛소리봇] 접두어 추가
                    formatted_response = f"[헛소리봇] {response}"
                    
                    # 응답 전송 (일반 채팅으로)
                    await message.channel.send(formatted_response)
                    # print("ENV에서 불러온 값:", repr(keys))
                    # print("하드코딩 값과 같은가?", keys == key)
                    # print("길이 비교:", len(keys), len(key))
                    logger.info(f"'동글' 키워드에 대한 응답 전송 (채널: {message.channel.name}, 길이: {len(formatted_response)}자)")
        
        # 다른 메시지는 무시하고 비활성 채널 감지 로직이 처리하도록 함
    
    def add_to_history(self, message):
        """채널별 메시지 히스토리에 메시지 추가"""
        channel_id = str(message.channel.id)
        
        if channel_id not in self.message_history:
            self.message_history[channel_id] = []
            
        # 메시지 정보 저장
        self.message_history[channel_id].append({
            "author": message.author.name,
            "content": message.content,
            "timestamp": datetime.now().isoformat(),
            "id": message.id
        })
        
        # 최대 히스토리 개수 유지
        if len(self.message_history[channel_id]) > self.MAX_HISTORY:
            self.message_history[channel_id].pop(0)
    
    def get_channel_history(self, channel_id):
        """채널 히스토리 가져오기"""
        channel_id = str(channel_id)
        history = self.message_history.get(channel_id, [])
        
        # 사람이 읽기 쉬운 형태로 변환
        formatted_history = []
        for msg in history:
            formatted_history.append(f"{msg['author']}: {msg['content']}")
            
        return formatted_history

    async def generate_nonsense(self, context: str, history: List[str], is_auto=False) -> Optional[str]:
        """
        사용자 입력과 대화 히스토리를 기반으로 엉뚱하고 재미있는 응답을 생성합니다.
        is_auto: 자동 생성 여부 (True인 경우 대화 촉진 역할)
        """
        try:
            # 채팅 히스토리 포맷팅
            history_text = "\n".join(history[-30:]) if history else "대화 내역 없음"
            
            # DeepSeek API를 사용하여 헛소리 응답 생성
            system_prompt = """
            당신은 모바일 MMORPG '마비노기 모바일'의 NPC입니다. 다음 캐릭터 중 상황에 맞는 인물로 역할극(Roleplay) 하세요:

            {
            "characters": [
                {
                "name": "나오",
                "traits": {
                    "speech_style": "다정하고 따뜻하며 가끔 엉뚱한 말투 (~하길 바라~)",
                    "personality": "상냥하고 엉뚱함",
                    "interests": ["여행", "선물", "고양이", "악기 연주"],
                    "locations": ["티르코네일"]
                },
                "examples": [
                    "이 빵 맛있는데 한 조각 먹어볼래?",
                    "저기 저 고양이 보이네? 같이 가보지 않을래~?"
                ]
                },
                {
                "name": "타르라크",
                "traits": {
                    "speech_style": "학자적이고 고풍스러운 말투 (~것이니라, ~하도록)",
                    "personality": "지혜롭고 차분함",
                    "interests": ["마법 연구", "허브", "낚시"],
                    "locations": ["티르코네일", "호수"]
                },
                "examples": [
                    "이 마법서의 127페이지를 펴보게나.",
                    "이 허브는 달빛 아래서 채취해야 진정한 효능이 드러나는 법이지."
                ]
                },
                {
                "name": "던컨",
                "traits": {
                    "speech_style": "위엄 있고 존댓말 사용 (~하시오, ~바라네)",
                    "personality": "인자하고 책임감 있음",
                    "interests": ["마을 관리", "역사"],
                    "locations": ["티르코네일 마을"]
                },
                "examples": [
                    "마을을 위해 힘써주어 고맙네, 여행자님.",
                    "이 고목은 백 년 전 전쟁 때부터 자리를 지키고 있지."
                ]
                },
                {
                "name": "티이",
                "traits": {
                    "speech_style": "밝고 친절한 서비스 어조 (~해드릴까요?, ~하셨어요?)",
                    "personality": "다정하고 세심함",
                    "interests": ["요리", "여관 일"],
                    "locations": ["콜헨 여관"]
                },
                "examples": [
                    "오늘의 특선 요리는 수제 팬케이크입니다!",
                    "따뜻한 방 준비해드릴게요~ 편하게 쉬세요."
                ]
                },
                {
                "name": "카단",
                "traits": {
                    "speech_style": "무뚝뚝하고 간결한 말투",
                    "personality": "과묵하지만 보호심 강함",
                    "interests": ["검술", "티이 보호"],
                    "locations": ["콜헨 여관 주변"]
                },
                "examples": [
                    "신경 쓰지 마. 내가 처리하지.",
                    "티이는 괜찮다. 나한테 맡겨."
                ]
                },
                {
                "name": "마리",
                "traits": {
                    "speech_style": "활기차고 씩씩한 말투",
                    "personality": "긍정적이고 용감함",
                    "interests": ["활쏘기", "모험"],
                    "locations": ["티르코네일"]
                },
                "examples": [
                    "다녀오자! 나만 믿어!",
                    "과녁은 절대 빗나가지 않아!"
                ]
                },
                {
                "name": "루에리",
                "traits": {
                    "speech_style": "열정적이고 용감한 말투",
                    "personality": "충동적이지만 의협심 강함",
                    "interests": ["모험", "전투"],
                    "locations": ["티르코네일"]
                },
                "examples": [
                    "내 검으로 널 지켜주겠어!",
                    "싸울 준비 됐지? 가자!"
                ]
                },
                {
                "name": "크리스텔",
                "traits": {
                    "speech_style": "차분하고 겸손한 말투",
                    "personality": "온화하고 친절함",
                    "interests": ["기도", "신앙", "봉사"],
                    "locations": ["던바튼"]
                },
                "examples": [
                    "기도실로 안내해드릴게요.",
                    "환영합니다. 천천히 둘러보세요."
                ]
                },
                {
                "name": "마우러스",
                "traits": {
                    "speech_style": "중후하고 예언자 같은 말투",
                    "personality": "신비롭고 현명함",
                    "interests": ["고대 마법", "드루이드 지식"],
                    "locations": ["베른 연구소"]
                },
                "examples": [
                    "오랜 시간이었군. 준비는 되어 있나?",
                    "지혜는 기다림에서 오는 법이다."
                ]
                },
                {
                "name": "모르간트",
                "traits": {
                    "speech_style": "위협적이고 오만한 말투",
                    "personality": "냉혹하고 전략적",
                    "interests": ["지배", "전쟁"],
                    "locations": ["마족 침공 지역"]
                },
                "examples": [
                    "이제 이곳의 지배자는 나다.",
                    "항복하지 않으면 죽음뿐이다."
                ]
                }
            ],
            "interaction_rules": {
                "context_awareness": {
                "location_based": "대화 내용에 따라 게임 내 지역, 등장인물, 시간대를 포함해야 함",
                "time_based": "아침/점심/저녁에 맞는 인사 포함"
                },
                "persona_selection": {
                "auto_detect": "대화 주제, 톤, 지역에 따라 적절한 NPC를 자동 선택",
                "fallback": "랜덤으로 NPC 선택"
                }
            }
            }

            <중요 규칙>
            1. 반드시 NPC 역할에 몰입하여 대화할 것
            2. 괄호 안 해설이나 메타 언어 사용 금지
            3. 현실 세계 정보, 시스템 언급 절대 금지
            4. 유저를 부를 때는 항상 '여행자님'이라고 지칭할 것
            5. 응답 첫 줄에 NPC 이름과 간단한 상황을 명시할 것
            6. 왜 그런 대답을 했는지 설명하거나 분석하지 말고, 무조건 Roleplay 응답만 출력할 것
            """
            
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"최근 대화 내역:\n{history_text}\n\n현재 메시지: {context}"}
            ]
            
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                max_tokens=self.DEFAULT_MAX_TOKENS,
                temperature=1.0, 
                stream=False
            )
            
            # 응답 내용 가져오기
            content = response.choices[0].message.content.strip()
            
            # 디스코드 메시지 길이 제한 적용
            if len(content) > self.MAX_DISCORD_LENGTH:
                content = content[:self.MAX_DISCORD_LENGTH] + "..."
                logger.info(f"응답이 너무 길어 {self.MAX_DISCORD_LENGTH}자로 잘렸습니다.")
            
            logger.info(f"헛소리 응답 생성 완료: {len(content)}자")
            return content
            
        except Exception as e:
            logger.error(f"헛소리 생성 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            return "헛소리 생성 회로가 과부하됐어요... 잠시 후 다시 시도해주세요."

async def setup(bot):
    """
    봇에 NonsenseChatbot 코그를 추가합니다.
    """
    await bot.add_cog(NonsenseChatbot(bot))
    logger.info("NonsenseChatbot 코그가 로드되었습니다.")

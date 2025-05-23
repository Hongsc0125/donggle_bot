import logging
import traceback
import discord
from discord.ext import commands, tasks
from discord import app_commands
from core.config import settings
from openai import OpenAI
from datetime import datetime
from db.session import SessionLocal
from queries.channel_query import select_chatbot_channel
import typing
from typing import List, Dict, Any, Optional

# 로거 설정
logger = logging.getLogger("cogs.chat_assistant")

# API 키 설정 (DeepSeek API 키 사용)
key = settings.DEEPSEEK_API_KEY

class SummaryAssistant(commands.Cog):
    """
    메시지 요약 도우미 - 채널의 대화 맥락을 기반으로 요약본을 제공하는 Discord 챗봇
    
    특징:
    - 채널의 최근 대화 맥락을 이해해 요약 생성
    - 유저가 안 읽은 내용을 요약하여 임퍼럴 메시지로 전송
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
        
        # 채널 목록 캐시
        self.chatbot_channels = {}
        
        # 유저별 마지막 읽은 메시지 ID
        self.last_read_message = {}  # {channel_id: {user_id: last_read_message_id}}
        
        # 사용자별 채널별 마지막 접속 시간
        self.last_user_activity = {}  # {channel_id: {user_id: last_activity_timestamp}}
    
    def cog_unload(self):
        """코그가 언로드될 때 호출되는 메서드"""
        pass
    
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
                
                logger.info(f"요약 봇 채널 {len(self.chatbot_channels)}개 로드됨")
        except Exception as e:
            logger.error(f"봇 채널 로드 중 오류: {e}")
            logger.error(traceback.format_exc())
    
    @commands.Cog.listener()
    async def on_ready(self):
        """봇이 준비되었을 때 호출되는 이벤트"""
        await self.load_chatbot_channels()
        logger.info("요약 어시스턴트가 준비되었습니다.")
    
    async def cog_load(self):
        """코그가 로드될 때 호출되는 메서드"""
        logger.info("요약 어시스턴트 코그가 로드되었습니다.")
        
        # 메시지 이벤트 등록 - 메시지 히스토리를 위해 필요
        self.bot.add_listener(self.on_message_create, "on_message")
    
    async def on_message_create(self, message):
        """메시지 이벤트 처리 - 히스토리 추적용"""
        # 봇 메시지는 무시
        if message.author.bot:
            return
        
        # 메시지 히스토리에 추가
        self.add_to_history(message)
    
    # 요약 명령어 - 채널의 일반 요약
    @app_commands.command(name="요약", description="현재 채널의 대화 내용을 요약합니다")
    @app_commands.describe(
        전송방식="요약을 받을 방식을 선택합니다 (공개: 채널에 공개적으로 표시, 개인: 개인만 보이는 메시지로 전송)", 
        메시지개수="요약할 최근 메시지 개수를 선택합니다"
    )
    async def summarize(self, interaction: discord.Interaction, 
                       전송방식: typing.Literal["공개", "개인"],
                       메시지개수: typing.Literal["50", "100", "300", "500"] = "100"):
        # 명령어 응답 지연 (서버에서 처리하는 데 시간이 걸릴 수 있으므로)
        await interaction.response.defer(ephemeral=True)
        
        # 채널 ID 확인
        channel_id = str(interaction.channel_id)
        user_id = str(interaction.user.id)
        
        # 현재 사용자의 활동 시간 업데이트
        self.update_user_activity_from_interaction(interaction)
        
        try:
            logger.info(f"요약 명령어 실행: 채널={channel_id}, 사용자={user_id}, 전송방식={전송방식}")
            # 요약할 메시지 가져오기
            messages_to_summarize = []
            is_private_mode = 전송방식 == "개인"
            
            # 메시지 개수 정수로 변환
            limit = int(메시지개수)
            logger.info(f"요약 설정: 전송방식={전송방식}, 메시지개수={limit}")
            
            # 최근 메시지 요약 (지정된 개수만큼)
            messages_to_summarize = await self.get_channel_history(channel_id, limit=limit)
            logger.info(f"요약할 메시지 개수: {len(messages_to_summarize)}")
            summary_type = "최근 메시지"
            additional_instruction = f"최근 {limit}개의 메시지를 요약해주세요."
        
            
            if not messages_to_summarize or len(messages_to_summarize) < 3:
                await interaction.followup.send("요약할 메시지가 충분하지 않습니다. 더 많은 대화가 필요합니다.", ephemeral=True)
                logger.warning(f"요약할 메시지 부족: 채널={channel_id}, 사용자={user_id}, 메시지개수={len(messages_to_summarize) if messages_to_summarize else 0}")
                return
            
            
            # 요약 생성
            summary = await self.generate_summary(messages_to_summarize)
            
            if not summary:
                await interaction.followup.send("요약을 생성할 수 없습니다. 나중에 다시 시도해주세요.", ephemeral=True)
                return
                
            # 임베드 생성
            embed = discord.Embed(
                # title=f"💬 {summary_type}{limit}개 메시지 요약 ",
                description=f"> {summary}",
                color=0x242429
            )
            
            # 현재 시간 추가
            embed.set_footer(text=f"{datetime.now().strftime('%Y-%m-%d %H:%M')} | {summary_type}{limit}개 메시지 요약")
            
            # 전송 방식에 따라 요약 전송
            if is_private_mode:  # 개인 메시지로 전송
                try:
                    # 개인 메시지로 임베드 전송
                    await interaction.user.send(embed=embed)
                    
                    # 요청한 채널에는 성공 메시지만 전송
                    await interaction.followup.send(f"{summary_type} 요약을 개인에게만 보이도록 전송했습니다.", ephemeral=True)
                    
                    logger.info(f"개인 임베드 요약 전송 완료 (사용자: {interaction.user.name}, 유형: {summary_type}, 길이: {len(summary)}자)")
                except Exception as e:
                    logger.error(f"개인 요약 전송 실패: {e}")
                    await interaction.followup.send("개인 메시지 전송 중 오류가 발생했습니다", ephemeral=True)
            else:  # 채널에 공개적으로 전송
                # 임베드로 공개 전송
                await interaction.channel.send(embed=embed)
                await interaction.followup.send("요약이 전송되었습니다.", ephemeral=True)
                logger.info(f"임베드 요약 전송 완료 (채널: {interaction.channel.name}, 유형: {summary_type}, 길이: {len(summary)}자)")
        
        except Exception as e:
            logger.error(f"요약 생성 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            await interaction.followup.send("요약 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.", ephemeral=True)
    
    def add_to_history(self, message):
        """채널별 메시지 히스토리에 메시지 추가 (마지막 읽은 메시지 추적용)"""
        channel_id = str(message.channel.id)
        
        # 채널 ID로 마지막 메시지 ID 저장 (읽은 메시지 추적용)
        if channel_id not in self.last_read_message:
            self.last_read_message[channel_id] = {}
            
        # 디버그 로그만 추가
        logger.debug(f"채널 {channel_id} 메시지 감지: {message.author.name} - {message.content[:30]}...")
    
    async def get_channel_history(self, channel_id, limit=100):
        channel_id = int(channel_id)  # Discord API는 정수 ID 사용
        
        logger.info(f"채널 {channel_id} 히스토리 요청: limit={limit}")
        
        try:
            # Discord API로 채널 객체 가져오기
            channel = self.bot.get_channel(channel_id)
            if not channel:
                logger.warning(f"채널 {channel_id} 찾을 수 없음")
                return []
                
            # 최근 메시지 가져오기
            messages = []
            async for msg in channel.history(limit=limit):
                # 봇 메시지 제외
                if msg.author.bot:
                    continue
                    
                messages.append(msg)
            
            # 시간 순서로 정렬 (가장 오래된 것이 먼저 오도록)
            messages.reverse()
            
            logger.info(f"채널 {channel_id} 히스토리 가져오기 성공: {len(messages)}개 메시지")
            
            # 사람이 읽기 쉽도록 형태로 변환 (길드 내 닉네임 사용)
            formatted_history = []
            for msg in messages:
                # 길드 내 닉네임 가져오기 (가능한 경우)
                try:
                    # 메시지가 서버에서 온 경우
                    if hasattr(msg, 'guild') and msg.guild is not None:
                        member = msg.guild.get_member(msg.author.id)
                        display_name = member.display_name if member else msg.author.name
                    else:
                        display_name = msg.author.name
                    
                    formatted_history.append(f"{display_name}: {msg.content}")
                except Exception as e:
                    # 오류 발생 시 기본 이름 사용
                    logger.error(f"닉네임 가져오기 오류: {e}")
                    formatted_history.append(f"{msg.author.name}: {msg.content}")
                
            return formatted_history
            
        except Exception as e:
            logger.error(f"채널 히스토리 가져오기 오류: {e}")
            return []

    def update_user_activity(self, message):
        """메시지 객체로부터 사용자의 활동 시간 업데이트"""
        channel_id = str(message.channel.id)
        user_id = str(message.author.id)
        
        # 채널별 사용자 활동 데이터 초기화
        if channel_id not in self.last_user_activity:
            self.last_user_activity[channel_id] = {}
            
        # 현재 사용자의 활동 시간 업데이트
        self.last_user_activity[channel_id][user_id] = datetime.now()
        
        # 마지막으로 읽은 메시지 ID 업데이트
        if channel_id not in self.last_read_message:
            self.last_read_message[channel_id] = {}
            
        # 현재 사용자가 읽은 메시지 ID 업데이트
        self.last_read_message[channel_id][user_id] = str(message.id)
            
        logger.debug(f"사용자 {user_id} 활동 시간 업데이트 (채널: {channel_id})")
    
    async def update_user_activity_from_interaction(self, interaction):
        """슬래시 명령어 상호작용에서 사용자의 활동 시간 업데이트"""
        channel_id = str(interaction.channel_id)
        user_id = str(interaction.user.id)
        
        # 채널별 사용자 활동 데이터 초기화
        if channel_id not in self.last_user_activity:
            self.last_user_activity[channel_id] = {}
            
        # 현재 사용자의 활동 시간 업데이트
        self.last_user_activity[channel_id][user_id] = datetime.now()
        
        # 마지막으로 읽은 메시지 ID 업데이트
        if channel_id not in self.last_read_message:
            self.last_read_message[channel_id] = {}
        
        try:
            # 채널의 마지막 메시지 ID 가져오기
            channel = self.bot.get_channel(int(channel_id))
            if channel:
                # 가장 최근 메시지 1개만 가져오기
                async for msg in channel.history(limit=1):
                    if not msg.author.bot:  # 봇 메시지 제외
                        self.last_read_message[channel_id][user_id] = str(msg.id)
                        break
                        
            logger.debug(f"사용자 {user_id} 활동 시간 업데이트 (채널: {channel_id}, 슬래시 명령어)")
        except Exception as e:
            logger.error(f"사용자 활동 업데이트 오류: {e}")

    async def get_unread_messages(self, channel_id, user_id, limit=100):
        channel_id = str(channel_id)
        user_id = str(user_id)
        
        logger.info(f"읽지 않은 메시지 검색: 채널={channel_id}, 사용자={user_id}, 최대개수={limit}")
        
        # 사용자의 마지막 읽은 메시지 ID 가져오기
        last_read_id = None
        if channel_id in self.last_read_message and user_id in self.last_read_message[channel_id]:
            last_read_id = self.last_read_message[channel_id][user_id]
            logger.info(f"사용자의 마지막 읽은 메시지 ID: {last_read_id}")
        else:
            logger.info(f"사용자의 마지막 읽은 메시지 기록 없음")
            
            # 마지막 읽은 메시지 기록 없는 경우, 지정된 개수의 메시지만 가져옴
            return await self.get_channel_history(channel_id, limit=limit)
        
        try:
            # Discord API로 채널 객체 가져오기
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                logger.warning(f"채널 {channel_id} 찾을 수 없음")
                return []
            
            # 최대 100개의 메시지 가져오기
            messages = []
            async for msg in channel.history(limit=100):
                # 봇 메시지 제외
                if msg.author.bot:
                    continue
                    
                messages.append(msg)
                # 마지막으로 읽은 메시지를 찾으면 중단
                if str(msg.id) == last_read_id:
                    break
            
            # 읽지 않은 메시지만 필터링 (마지막 읽은 메시지 이후의 메시지들)
            unread_messages = []
            found_last_read = False
            
            # 시간 순서로 정렬 (가장 오래된 것이 먼저 오도록)
            messages.reverse()
            
            for msg in messages:
                if str(msg.id) == last_read_id:
                    found_last_read = True
                    continue  # 마지막으로 읽은 메시지는 제외
                
                if found_last_read and str(msg.author.id) != user_id:  # 자기 메시지 제외
                    # 길드 내 닉네임 가져오기
                    try:
                        if hasattr(msg, 'guild') and msg.guild is not None:
                            member = msg.guild.get_member(msg.author.id)
                            display_name = member.display_name if member else msg.author.name
                        else:
                            display_name = msg.author.name
                            
                        unread_messages.append(f"{display_name}: {msg.content}")
                    except Exception as e:
                        logger.error(f"닉네임 가져오기 오류: {e}")
                        unread_messages.append(f"{msg.author.name}: {msg.content}")
            
            logger.info(f"읽지 않은 메시지 검색 결과: {len(unread_messages)}개 발견")
            return unread_messages
        
        except Exception as e:
            logger.error(f"읽지 않은 메시지 검색 오류: {e}")
            return []
        
        return unread_messages

    async def generate_summary(self, history: List[str], additional_instruction: str = "") -> Optional[str]:
        """
        대화 히스토리를 기반으로 요약을 생성합니다.
        """
        try:
            # 채팅 히스토리 포맷팅
            history_text = "\n".join(history) if history else "대화 내역 없음"
            
            # 추가 지시사항 확인
            instruction = "Please summarize recent conversations that are concise but do not miss the core. Please respond in the language you used in the conversation."
            if additional_instruction:
                instruction = f"{additional_instruction}. {instruction}"
            
            messages = [
                {"role": "system", "content": "You are a Discord conversation summary assistant. Please summarize the recent conversation concisely but do not miss the core. Please respond in the language you used in the conversation."},
                {"role": "user", "content": f"Here is the recent conversation content of Discord channel:\n\n{history_text}\n\n{instruction}"}
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
            
            logger.info(f"요약 생성 완료: {len(content)}자")
            return content
            
        except Exception as e:
            logger.error(f"요약 생성 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            return "요약 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."

async def setup(bot):
    """
    봇에 SummaryAssistant 코그를 추가합니다.
    """
    await bot.add_cog(SummaryAssistant(bot))
    logger.info("SummaryAssistant 코그가 로드되었습니다.")

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
        
        # 메시지 캠시 (채널별로 최근 대화 저장)
        self.message_history = {}
        self.MAX_HISTORY = 50  # 50개 메시지로 확장
        
        # 채널별 마지막 메시지 시간 추적
        self.last_message_time = {}
        
        # 채널 목록 캠시
        self.chatbot_channels = {}
        # 메시지 캐시 (채널별로 최근 대화 저장)
        self.message_history = {}
        self.MAX_HISTORY = 50  # 50개 메시지로 확장
        
        # 채널별 마지막 메시지 시간 추적
        self.last_message_time = {}
        
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
        전송_방식="요약을 받을 방식을 선택합니다 (공개: 채널에 공개적으로 표시, 개인: 개인만 보이는 메시지로 전송)", 
        요약_범위="요약할 메시지의 범위를 선택합니다 (최근: 최근 50개 메시지, 안읽은것: 읽지 않은 메시지만)",
    )
    async def summarize(self, interaction: discord.Interaction, 
                       전송_방식: typing.Literal["공개", "개인"],
                       요약_범위: typing.Literal["최근", "안읽은것"]):
        # 명령어 응답 지연 (서버에서 처리하는 데 시간이 걸릴 수 있으므로)
        await interaction.response.defer(ephemeral=True)
        
        # 채널 ID 확인
        channel_id = str(interaction.channel_id)
        user_id = str(interaction.user.id)
        
        # 현재 사용자의 활동 시간 업데이트
        self.update_user_activity_from_interaction(interaction)
        
        try:
            # 요약할 메시지 가져오기
            messages_to_summarize = []
            is_private_mode = 전송_방식 == "개인"
            
            # 요약 범위에 따라 메시지 선택
            if 요약_범위 == "안읽은것":
                # 읽지 않은 메시지만 요약
                messages_to_summarize = self.get_unread_messages(channel_id, user_id)
                summary_type = "안읽은 메시지"
                additional_instruction = "사용자가 읽지 않은 내용만 요약해주세요."
            else:  # "최근"
                # 최근 50개 메시지 요약
                messages_to_summarize = self.get_channel_history(channel_id, limit=50)
                summary_type = "최근 메시지"
                additional_instruction = "최근 50개의 메시지를 요약해주세요."
            
            # 메시지 검사
            if not messages_to_summarize or len(messages_to_summarize) < 3:
                if 요약_범위 == "읽지않음":
                    await interaction.followup.send("읽지 않은 메시지가 없거나 충분하지 않습니다.", ephemeral=True)
                else:
                    await interaction.followup.send("요약할 메시지가 충분하지 않습니다. 더 많은 대화가 필요합니다.", ephemeral=True)
                return
            
            # 사용자가 입력한 추가 지시사항이 있는 경우 추가
            if 추가_지시사항:
                additional_instruction = f"{additional_instruction}\n{추가_지시사항}"
            
            # 요약 생성
            summary = await self.generate_summary(messages_to_summarize, additional_instruction)
            
            if not summary:
                await interaction.followup.send("요약을 생성할 수 없습니다. 나중에 다시 시도해주세요.", ephemeral=True)
                return
                
            # [요약] 접두어 추가
            formatted_response = f"[요약 - {summary_type}] {summary}"
            
            # 전송 방식에 따라 요약 전송
            if is_private_mode:  # 개인 메시지로 전송
                try:
                    # 개인 메시지로 전송
                    await interaction.user.send(formatted_response)
                    
                    # 요청한 채널에는 성공 메시지만 전송
                    await interaction.followup.send(f"{summary_type} 요약을 개인에게만 보이도록 전송했습니다.", ephemeral=True)
                    
                    logger.info(f"개인 요약 전송 완료 (사용자: {interaction.user.name}, 유형: {summary_type}, 길이: {len(summary)}자)")
                except Exception as e:
                    logger.error(f"개인 요약 전송 실패: {e}")
                    await interaction.followup.send("개인 메시지 전송 중 오류가 발생했습니다", ephemeral=True)
            else:  # 채널에 공개적으로 전송
                # 포맷팅된 요약 전송 (모든 사용자가 볼 수 있게 ephemeral=False)
                await interaction.channel.send(formatted_response)
                logger.info(f"요약 전송 완료 (채널: {interaction.channel.name}, 유형: {summary_type}, 길이: {len(summary)}자)")
        
        except Exception as e:
            logger.error(f"요약 생성 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            await interaction.followup.send("요약 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.", ephemeral=True)
    
    def add_to_history(self, message):
        """채널별 메시지 히스토리에 메시지 추가"""
        channel_id = str(message.channel.id)
        
        if channel_id not in self.message_history:
            self.message_history[channel_id] = []
            
        # 메시지 정보 저장
        self.message_history[channel_id].append({
            "author": message.author.name,
            "author_id": str(message.author.id),
            "content": message.content,
            "timestamp": datetime.now().isoformat(),
            "id": message.id
        })
        
        # 최대 히스토리 개수 유지
        if len(self.message_history[channel_id]) > self.MAX_HISTORY:
            self.message_history[channel_id].pop(0)
    
    def get_channel_history(self, channel_id, limit=None):
        """채널 히스토리 가져오기
        
        Args:
            channel_id (str): 채널 ID
            limit (int, optional): 가져올 최대 메시지 수. 기본값은 None (모든 메시지 반환)
        
        Returns:
            list: 메시지 히스토리 목록
        """
        channel_id = str(channel_id)
        if channel_id not in self.message_history:
            return []
        
        # 전체 히스토리 가져오기
        history = self.message_history[channel_id]
        
        # limit이 지정된 경우 최근 메시지만 반환
        if limit and len(history) > limit:
            history = history[-limit:]
        
        # 사람이 읽기 쉽도록 형태로 변환
        formatted_history = []
        for msg in history:
            formatted_history.append(f"{msg['author']}: {msg['content']}")
            
        return formatted_history

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
        if len(self.message_history.get(channel_id, [])) > 0:
            last_msg_id = self.message_history[channel_id][-1].get("id")
            self.last_read_message[channel_id][user_id] = last_msg_id
            
        logger.debug(f"사용자 {user_id} 활동 시간 업데이트 (채널: {channel_id})")
    
    def update_user_activity_from_interaction(self, interaction):
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
            
        # 현재 사용자가 읽은 메시지 ID 업데이트 (마지막 메시지 기준)
        if len(self.message_history.get(channel_id, [])) > 0:
            last_msg_id = self.message_history[channel_id][-1].get("id")
            self.last_read_message[channel_id][user_id] = last_msg_id
            
        logger.debug(f"사용자 {user_id} 활동 시간 업데이트 (채널: {channel_id}, 슬래시 명령어)")

    def get_unread_messages(self, channel_id, user_id):
        """사용자가 읽지 않은 메시지 가져오기"""
        channel_id = str(channel_id)
        user_id = str(user_id)
        
        # 채널 히스토리 가져오기
        history = self.message_history.get(channel_id, [])
        
        # 사용자의 마지막 읽은 메시지 ID 가져오기
        last_read_id = None
        if channel_id in self.last_read_message and user_id in self.last_read_message[channel_id]:
            last_read_id = self.last_read_message[channel_id][user_id]
        
        # 읽지 않은 메시지 찾기
        unread_messages = []
        found_last_read = False if last_read_id else True
        
        for msg in history:
            msg_id = msg.get("id")
            
            # 마지막 읽은 메시지를 찾았다면 이후 메시지를 추가
            if found_last_read:
                # 자기 자신의 메시지는 제외
                if user_id != msg.get("author_id", ""):
                    unread_messages.append(f"{msg['author']}: {msg['content']}")
            elif msg_id == last_read_id:
                found_last_read = True
        
        return unread_messages

    async def generate_summary(self, history: List[str], additional_instruction: str = "") -> Optional[str]:
        """
        대화 히스토리를 기반으로 요약을 생성합니다.
        """
        try:
            # 채팅 히스토리 포맷팅
            history_text = "\n".join(history[-50:]) if history else "대화 내역 없음"
            
            # 추가 지시사항 확인
            instruction = "최근 대화 내용을 간결하게 요약해주세요."
            if additional_instruction:
                instruction = f"{additional_instruction}. {instruction}"
            
            messages = [
                {"role": "system", "content": "당신은 Discord 대화를 요약해주는 도우미입니다. 다음 지시사항에 따라 최근 대화를 요약해주세요."},
                {"role": "user", "content": f"다음은 Discord 채널의 최근 대화 내용입니다:\n\n{history_text}\n\n{instruction}"}
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

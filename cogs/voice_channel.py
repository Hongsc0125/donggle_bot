import discord
from discord.ext import commands
import logging
import asyncio
from datetime import datetime, timedelta

from db.session import SessionLocal
from core.utils import interaction_response, interaction_followup
from queries.channel_query import select_voice_channels
from queries.recruitment_query import select_recruitment, select_participants
from queries.thread_query import update_complete_recruitment, select_complete_thread

logger = logging.getLogger(__name__)

class VoiceChannelCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.temp_channels = {}  # 임시 채널 저장: {channel_id: {"owner": user_id, "thread_id": thread_id, "recru_id": recru_id}}
        self.user_channels = {}  # 사용자별 채널 매핑: {user_id: channel_id}

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """음성 채널 상태가 변경될 때 호출되는 이벤트 리스너"""
        try:
            # 디버그 로그 추가
            # logger.info(f"음성 상태 변경: 사용자 {member.display_name} ({member.id}), "
            #            f"이전: {before.channel.name if before.channel else 'None'}, "
            #            f"이후: {after.channel.name if after.channel else 'None'}")
            
            # 처음 음성채널 입장 시
            if before.channel is None and after.channel is not None:
                # logger.info(f"사용자 {member.display_name}이(가) 채널 {after.channel.name} ({after.channel.id})에 입장함")
                await self.handle_voice_join(member, after.channel)
            
            # 음성채널 퇴장 시
            elif before.channel is not None and (after.channel is None or after.channel.id != before.channel.id):
                # logger.info(f"사용자 {member.display_name}이(가) 채널 {before.channel.name} ({before.channel.id})에서 퇴장함")
                await self.handle_voice_leave(member, before.channel)
                
        except Exception as e:
            logger.error(f"음성 상태 업데이트 처리 중 오류 발생: {str(e)}")

    async def handle_voice_join(self, member, channel):
        """사용자가 음성 채널에 입장했을 때 처리"""
        try:
            # 추가 로깅
            # logger.info(f"음성 채널 입장 처리 시작: 사용자 {member.display_name}, 채널 {channel.name} ({channel.id})")
            
            with SessionLocal() as db:
                # 부모 음성채널 ID 목록 조회 (새 테이블에서)
                # logger.info(f"부모 음성채널 ID 목록 조회 시작: 길드 ID {member.guild.id}")
                parent_voice_ch_ids = select_voice_channels(db, member.guild.id)
                # logger.info(f"부모 음성채널 ID 목록 조회 결과: {parent_voice_ch_ids}")
                
                # 입장한 채널이 부모 음성채널 중 하나인지 확인
                if str(channel.id) in parent_voice_ch_ids:
                    # logger.info(f"채널 {channel.id}는 부모 음성채널입니다. 임시 채널 생성 절차 시작.")
                    
                    # 이미 임시 채널이 있는지 확인
                    if member.id in self.user_channels:
                        existing_channel_id = self.user_channels[member.id]
                        existing_channel = member.guild.get_channel(int(existing_channel_id))
                        if existing_channel:
                            logger.info(f"사용자 {member.display_name}의 기존 임시 채널 발견: {existing_channel.name}")
                            # 기존 임시 채널로 이동
                            await member.move_to(existing_channel)
                            return
                    
                    # 임시 채널 생성
                    # logger.info(f"새 임시 채널 생성 시작: 사용자 {member.display_name}, 부모 채널 ID {channel.id}")
                    await self.create_temp_voice_channel(member, str(channel.id))
                else:
                    logger.info(f"채널 {channel.id}는 부모 음성채널이 아닙니다. 설정된 부모 채널: {parent_voice_ch_ids}")
        except Exception as e:
            logger.error(f"음성 채널 입장 처리 중 오류 발생: {str(e)}")

    async def handle_voice_leave(self, member, channel):
        """사용자가 음성 채널에서 퇴장했을 때 처리"""
        try:
            # 임시 채널인지 확인
            if str(channel.id) in self.temp_channels:
                # 채널에 남아 있는 사용자 수 확인
                if len(channel.members) == 0:
                    # 채널 삭제
                    await self.delete_temp_voice_channel(channel)
                elif self.temp_channels[str(channel.id)]["owner"] == member.id:
                    # 채널 소유자가 나갔을 때 새 소유자 지정
                    if channel.members:
                        new_owner = channel.members[0]
                        self.temp_channels[str(channel.id)]["owner"] = new_owner.id
                        self.user_channels[new_owner.id] = str(channel.id)
                        
                        # 이름 변경 (recru_id가 있으면 원래 형식으로 채널명 유지)
                        recru_id = self.temp_channels[str(channel.id)].get("recru_id")
                        if recru_id:
                            with SessionLocal() as db:
                                recruitment_result = select_recruitment(db, recru_id)
                                if recruitment_result:
                                    creator_name = new_owner.display_name
                                    channel_name = f"{creator_name}의 {recruitment_result['dungeon_type']} 파티"
                                    await channel.edit(name=channel_name)
                                else:
                                    await channel.edit(name=f"{new_owner.display_name}의 음성채널")
                        else:
                            await channel.edit(name=f"{new_owner.display_name}의 음성채널")
                
                # 사용자-채널 매핑에서 제거
                if member.id in self.user_channels:
                    del self.user_channels[member.id]
        except Exception as e:
            logger.error(f"음성 채널 퇴장 처리 중 오류 발생: {str(e)}")

    async def create_temp_voice_channel(self, member, parent_voice_ch_id):
        """임시 음성 채널 생성"""
        try:
            guild = member.guild
            category = None
            recru_id = None
            channel_name = None
            thread_id = None
            participants = []
            
            # 부모 채널의 카테고리 가져오기
            parent_channel = guild.get_channel(int(parent_voice_ch_id))
            if parent_channel:
                category = parent_channel.category
            
            # 모집 정보 찾기 - DB 관련 스레드 검색
            with SessionLocal() as db:
                # 사용자가 참여 중인 스레드 검색
                for g in self.bot.guilds:
                    if g.id == guild.id:
                        for thread in g.threads:
                            if member in thread.members:
                                # 스레드에서 모집 ID 찾기
                                async for message in thread.history(limit=10):
                                    if message.embeds and len(message.embeds) > 0 and message.embeds[0].footer and message.embeds[0].footer.text:
                                        found_recru_id = message.embeds[0].footer.text
                                        # 모집 정보 및 스레드 정보 조회
                                        recruitment_result = select_recruitment(db, found_recru_id)
                                        if recruitment_result:
                                            recru_id = found_recru_id
                                            thread_id = thread.id
                                            
                                            # 파티원 목록 가져오기
                                            participants_list = select_participants(db, recru_id)
                                            if participants_list:
                                                # 파티원 멤버 객체 가져오기
                                                for user_id in participants_list:
                                                    try:
                                                        participant = await guild.fetch_member(int(user_id))
                                                        if participant:
                                                            participants.append(participant)
                                                    except Exception as e:
                                                        logger.error(f"파티원 정보 조회 중 오류: {e}")
                                            
                                            # 채널명 설정
                                            creator_name = member.display_name
                                            if str(member.id) == recruitment_result["create_user_id"]:
                                                channel_name = f"{creator_name}의 {recruitment_result['dungeon_type']} 파티"
                                                break
            
            # 채널명이 설정되지 않은 경우 기본값 사용
            if not channel_name:
                channel_name = f"{member.display_name}의 음성채널"
            
            # 권한 설정 - 기본적으로 모든 사용자에게 접근 불가
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=True),
                guild.me: discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True),
                member: discord.PermissionOverwrite(view_channel=True, connect=True, move_members=True, mute_members=True)
            }
            
            # 파티원들에게 권한 부여
            for participant in participants:
                if participant.id != member.id:  # 이미 추가한 채널 생성자는 제외
                    overwrites[participant] = discord.PermissionOverwrite(view_channel=True, connect=True)
            
            # 채널 생성
            temp_channel = await guild.create_voice_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                reason="임시 음성채널 생성"
            )
            
            # 사용자를 새 채널로 이동
            await member.move_to(temp_channel)
            
            # 채널 정보 저장
            self.temp_channels[str(temp_channel.id)] = {
                "owner": member.id, 
                "thread_id": thread_id,
                "recru_id": recru_id
            }
            self.user_channels[member.id] = str(temp_channel.id)
            
            # 스레드에 초대 링크 전송 (recru_id가 있을 때만)
            if recru_id:
                await self.send_invite_to_thread(member, temp_channel, recru_id)
            
            logger.info(f"임시 음성채널이 생성되었습니다: {channel_name} (ID: {temp_channel.id})")
            return temp_channel
            
        except Exception as e:
            logger.error(f"임시 음성채널 생성 중 오류 발생: {str(e)}")
            return None

    async def delete_temp_voice_channel(self, channel):
        """임시 음성 채널 삭제"""
        try:
            # 채널 정보 삭제
            if str(channel.id) in self.temp_channels:
                del self.temp_channels[str(channel.id)]
            
            # 채널 삭제
            await channel.delete(reason="임시 음성채널 삭제 - 사용자 없음")
            logger.info(f"임시 음성채널이 삭제되었습니다: {channel.name} (ID: {channel.id})")
            
        except Exception as e:
            logger.error(f"임시 음성채널 삭제 중 오류 발생: {str(e)}")

    async def send_invite_to_thread(self, member, voice_channel, recru_id=None):
        """스레드에 초대 링크 전송"""
        try:
            thread = None
            
            # recru_id가 있으면 DB에서 complete_thread_ch_id 조회
            if recru_id:
                with SessionLocal() as db:
                    thread_id = select_complete_thread(db, recru_id)
                    if thread_id:
                        # 스레드 찾기
                        for guild in self.bot.guilds:
                            thread = guild.get_thread(int(thread_id))
                            if thread:
                                break
            
            # recru_id가 없거나 스레드를 찾지 못하면 메시지 전송하지 않음
            if not thread:
                logger.info("파티모집완료된 스레드가 아니므로 초대 메시지를 전송하지 않습니다.")
                return
            
            # 초대 링크 생성 및 전송
            invite = await voice_channel.create_invite(max_age=3600)
            
            # 스레드 ID 저장
            self.temp_channels[str(voice_channel.id)]["thread_id"] = thread.id
            
            # 스레드에 메시지 전송
            embed = discord.Embed(
                title="🔊 음성채널이 생성되었습니다!",
                description=f"아래 방법으로 음성채널에 참여할 헤주세요.\n\n1️⃣ 서버 채널 목록에서 '{voice_channel.name}' 채널을 찾아 입장\n\n2️⃣ 좌측의 링크를 눌러 입장: [음성채널 참여하기]({invite})",
                color=0x5865F2
            )
            await thread.send(embed=embed)
            
        except Exception as e:
            logger.error(f"스레드 초대 링크 전송 중 오류 발생: {str(e)}")

# Cog를 등록하는 설정 함수
async def setup(bot):
    await bot.add_cog(VoiceChannelCog(bot))
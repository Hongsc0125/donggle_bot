import discord
from discord.ext import commands
import asyncio
import logging
import functools
from typing import Callable, Coroutine, List, Any
import time


logger = logging.getLogger(__name__)

# 2초 후 삭제되는 ephemeral 메시지 전송
async def interaction_response(interaction: discord.Interaction, message: str, ephemeral: bool = True):
    try:
        if ephemeral:
            msg = await interaction.response.send_message(message, ephemeral=True)
            # await asyncio.sleep(2)
            # await msg.delete()
    except discord.HTTPException as e:
        logger.error(f"Interaction response error: {e}")

# 2초 후 삭제되는 ephemeral followup 메시지 전송
async def interaction_followup(interaction: discord.Interaction, message: str, ephemeral: bool = True):
    try:
        if ephemeral:
            msg = await interaction.followup.send(message, ephemeral=True)
            # await asyncio.sleep(2)
            # await msg.delete()
    except discord.HTTPException as e:
        logger.error(f"Interaction followup error: {e}")

# 우선순위 데코레이터
def with_priority(priority):
    """함수에 우선순위를 지정하는 데코레이터"""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            if hasattr(self, 'bot') and hasattr(self.bot, 'schedule_task'):
                return self.bot.schedule_task(priority, func, self, *args, **kwargs)
            return await func(self, *args, **kwargs)
        return wrapper
    return decorator

# 작업 그룹화 유틸리티
async def execute_concurrently(coroutines: List[Coroutine]) -> List[Any]:
    """코루틴 목록을 동시에 실행하는 유틸리티 함수"""
    if not coroutines:
        return []
        
    try:
        results = await asyncio.gather(*coroutines, return_exceptions=True)
        
        # 예외 처리 및 로깅
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"동시 실행 중 오류 (작업 {i}): {str(result)}")
        
        # 성공한 결과만 반환
        return [r for r in results if not isinstance(r, Exception)]
    except Exception as e:
        logger.error(f"동시 실행 중 오류 발생: {str(e)}")
        return []

# 작업 배치 처리 데코레이터
def batch_operation(size=10, timeout=5.0):
    """배치 처리를 위한 데코레이터"""
    def decorator(func):
        # 각 함수별 배치 상태 저장
        batches = {}
        
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # 클래스 메소드인 경우 self는 첫 번째 인자
            self = args[0] if args else None
            instance_id = id(self) if self else "no_instance"
            
            # 함수별 고유 키 생성
            key = f"{func.__name__}_{instance_id}"
            
            if key not in batches:
                batches[key] = {
                    "items": [],
                    "last_process": time.time(),
                    "task": None
                }
            
            batch = batches[key]
            
            # 만약 items 파라미터가 직접 전달된 경우 (이미 배치화된 항목들)
            if len(args) > 1 and isinstance(args[1], list) and not kwargs.get('items'):
                # 직접 처리 모드 - process_batch 호출을 건너뛰고 원래 함수 바로 호출
                return await func(self, args[1])
            
            # 현재 항목 추가 (self 제외)
            if len(args) > 1:
                item_data = (args[1:], kwargs)
            else:
                item_data = ((), kwargs)
                
            batch["items"].append(item_data)
            
            # 배치 크기 도달 또는 시간 초과 시 처리
            if len(batch["items"]) >= size or (time.time() - batch["last_process"]) > timeout:
                return await process_batch(key, func, self)
                
            # 아직 배치가 다 차지 않았으면 배치 처리 태스크 예약
            if not batch["task"] or batch["task"].done():
                batch["task"] = asyncio.create_task(
                    schedule_batch_processing(key, func, self, timeout)
                )
            
            return None  # 배치 처리중이므로 결과 없음
            
        async def schedule_batch_processing(key, func, self, wait_time):
            await asyncio.sleep(wait_time)
            if key in batches and batches[key]["items"]:
                await process_batch(key, func, self)
        
        async def process_batch(key, func, self):
            if key not in batches:
                return None
                
            batch = batches[key]
            items = batch["items"].copy()
            batch["items"] = []
            batch["last_process"] = time.time()
            
            if not items:
                return None
                
            # 배치 항목들 처리
            try:
                # self와 함께 items를 전달
                return await func(self, items)
            except Exception as e:
                logger.error(f"{func.__name__} 배치 처리 중 오류: {str(e)}")
                return None
                
        return wrapper
    return decorator
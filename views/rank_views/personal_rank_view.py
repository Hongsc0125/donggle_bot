import discord

def _build_rank_embed(character_name: str, server_name: str, class_name: str,
                        rank_position: str, power_value: str, change_amount: int,
                        change_type: str, footer_text: str) -> discord.Embed:
    # 순위 변동에 따른 색상 및 아이콘 결정
    if change_amount == 0:
        # 변동 없음 - 항상 회색으로 처리
        embed_color = 0x95A5A6  # 회색
        change_emoji = "-"
        change_text = change_emoji
    elif change_type == "up":
        embed_color = 0x57F287  # 초록색
        change_emoji = "↑"
        change_text = f"{change_emoji} {change_amount}"
    elif change_type == "down":
        embed_color = 0xED4245  # 빨간색
        change_emoji = "↓"
        change_text = f"{change_emoji} {change_amount}"
    else:
        # 알 수 없는 타입 - 기본 회색
        embed_color = 0x95A5A6
        change_text = "-"

    # 임베드 생성
    embed = discord.Embed(
        title=f"🏆 {character_name}",
        color=embed_color,
        description=f"**클래스**: {class_name} \n **서버**: {server_name}",
    )

    # 필드 추가
    embed.add_field(name="🥇 랭킹", value=f"```{rank_position}```", inline=True)
    embed.add_field(name="⚔️ 전투력", value=f"```{power_value}```", inline=True)
    embed.add_field(name="📊 순위 변동", value=f"```{change_text}```", inline=True)

    embed.set_footer(text=footer_text)
    return embed

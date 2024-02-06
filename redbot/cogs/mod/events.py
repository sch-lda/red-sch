import logging
from datetime import timezone
from collections import defaultdict, deque
from typing import List, Optional
from AAA3A_utils import Cog, CogsUtils, Menu
from redbot.core.utils.mod import get_audit_reason
import requests
import discord
from redbot.core import i18n, modlog, commands
from redbot.core.utils.mod import is_mod_or_superior
from .abc import MixinMeta
from .utils import is_allowed_by_hierarchy

_ = i18n.Translator("Mod", __file__)
log = logging.getLogger("red.mod")


class Events(MixinMeta):
    """
    This is a mixin for the core mod cog
    Has a bunch of things split off to here.
    """
    async def repeattosoftban(self, guild, author, message, channel, member, reason):
        guild = guild
        author = author
        message = message

        if author == member:
            log.info("cannot selfban")
            return

        audit_reason = get_audit_reason(author, reason, shorten=True)

        try:  # We don't want blocked DMs preventing us from banning
            msg = await member.send(
                _(
                    "你已被踢出,最近一天的消息已被删除."
                    "这通常是因为你的账号在群组内发送广告被管理员判定为广告机器人账号.\n"
                    "请检查账号状态并修改密码以排除盗号隐患.之后你可以通过此链接重新加入server. https://discord.gg/7GuNzajfhD"
                )
            )
        except discord.HTTPException:
            msg = None
        try:
            await guild.ban(member, reason=audit_reason, delete_message_seconds=86400)
        except discord.errors.Forbidden:
            log.info("My role is not high enough to softban that user.")
            if msg is not None:
                await msg.delete()
            return
        except discord.HTTPException:
            log.exception(
                "%s (%s) attempted to softban %s (%s), but an error occurred trying to ban them.",
                author,
                author.id,
                member,
                member.id,
            )
            return
        try:
            await guild.unban(member)
        except discord.HTTPException:
            log.exception(
                "%s (%s) attempted to softban %s (%s),"
                " but an error occurred trying to unban them.",
                author,
                author.id,
                member,
                member.id,
            )
            return
        else:
            log.info(
                "%s (%s) softbanned %s (%s), deleting 1 day worth of messages.",
                author,
                author.id,
                member,
                member.id,
            )
            await modlog.create_case(
                self.bot,
                guild,
                message.created_at,
                "softban",
                member,
                author,
                reason,
                until=None,
                channel=None,
            )
            await channel.send(_("清理了一个广告机"))

    async def check_duplicates(self, message):
        
        guild = message.guild
        author = message.author
        channel=message.channel
        member=author.id
        guild_cache = self.cache.get(guild.id, None)
        if guild_cache is None:
            repeats = await self.config.guild(guild).delete_repeats()
            if repeats == -1:
                log.info(-1)
                return False
            guild_cache = self.cache[guild.id] = defaultdict(lambda: deque(maxlen=6))
        
        if not message.content:
            return False
            # Off-topic # 频道公告 # mod-only # 规则
        if channel.id == 976462395427921940 or channel.id == 608168595314180106 or channel.id == 970972545564168232 or channel.id == 877000289146798151:
        
            return False
        if author.id == 97952414625182515 or author.id == 381096304153198604 or author.id == 522817015220666374 or author.id == 416781937059823619 or author.id == 1044589526116470844 or author.id == 803674604999934012:
            
            return False

        guild_cache[author].append(message.content)
        msgs = guild_cache[author]

        if len(msgs) > 2 and len(msgs) < 6 and len(set(msgs)) == 1:
            try:
                await message.delete()
                await message.channel.send(f"<@{author.id}>.Discord ID:({author.id}),如果你是人类,立即停止发送这条信息!继续发送重复消息将被识别为广告机踢出!", delete_after = 60)
                log.warning(
                        "已移除来自 ({member}) 的重复消息 在 {guild}".format(
                            member=author.id, guild=guild.id
                        )
                    )
                return True
            except discord.HTTPException:
                pass
        if len(msgs) == 6 and len(set(msgs)) == 1:
            try:
                ysch = self.bot.get_user(1044589526116470844)
                await self.repeattosoftban(guild, ysch, message, channel, author, "[自动]多次重复内容轰炸")
                await message.channel.send(f"<@{author.id}>.Discord ID:({author.id}),连续发送六条重复消息,鉴定为广告机,已全部撤回并踢出.")

                log.warning(
                        "已移除用户 ({member}) 在 {guild}".format(
                            member=author.id, guild=guild.id
                        )
                    )
                log.info(len(msgs))
                return True
            except discord.HTTPException:
                pass
        return False

    async def check_mention_spam(self, message):
        guild, author = message.guild, message.author
        mention_spam = await self.config.guild(guild).mention_spam.all()

        if mention_spam["strict"]:  # if strict is enabled
            mentions = len(message.raw_mentions) + len(message.raw_role_mentions)
        else:  # if not enabled
            mentions = len(set(message.mentions)) + len(set(message.role_mentions))

        if mention_spam["ban"]:
            if mentions >= mention_spam["ban"]:
                try:
                    await guild.ban(author, reason=_("Mention spam (Autoban)"))
                except discord.HTTPException:
                    log.warning(
                        "Failed to ban a member ({member}) for mention spam in server {guild}.".format(
                            member=author.id, guild=guild.id
                        )
                    )
                else:
                    await modlog.create_case(
                        self.bot,
                        guild,
                        message.created_at,
                        "ban",
                        author,
                        guild.me,
                        _("Mention spam (Autoban)"),
                        until=None,
                        channel=None,
                    )
                    return True

        if mention_spam["kick"]:
            if mentions >= mention_spam["kick"]:
                try:
                    await guild.kick(author, reason=_("Mention Spam (Autokick)"))
                except discord.HTTPException:
                    log.warning(
                        "Failed to kick a member ({member}) for mention spam in server {guild}".format(
                            member=author.id, guild=guild.id
                        )
                    )
                else:
                    await modlog.create_case(
                        self.bot,
                        guild,
                        message.created_at,
                        "kick",
                        author,
                        guild.me,
                        _("Mention spam (Autokick)"),
                        until=None,
                        channel=None,
                    )
                    return True

        if mention_spam["warn"]:
            if mentions >= mention_spam["warn"]:
                try:
                    await author.send(_("Please do not mass mention people!"))
                except (discord.HTTPException, discord.Forbidden):
                    try:
                        await message.channel.send(
                            _("{member}, Please do not mass mention people!").format(
                                member=author.mention
                            )
                        )
                    except (discord.HTTPException, discord.Forbidden):
                        log.warning(
                            "Failed to warn a member ({member}) for mention spam in server {guild}".format(
                                member=author.id, guild=guild.id
                            )
                        )
                        return False

                await modlog.create_case(
                    self.bot,
                    guild,
                    message.created_at,
                    "warning",
                    author,
                    guild.me,
                    _("Mention spam (Autowarn)"),
                    until=None,
                    channel=None,
                )
                return True
        return False
    
    async def muteadacc(self, message: discord.Message):
        guildid = message.guild.id
        if guildid != 388227343862464513:
            return
        async with self.config.user(message.author).iftrusted() as trusted:
            if trusted:
                return
        Authorization = await self.bot.get_shared_api_tokens("dc2auth")
        if Authorization.get("auth") is None:
            return
        userid = message.author.id
        url = f"https://discord.com/api/v9/users/{userid}/profile?with_mutual_guilds=true&with_mutual_friends_count=false&guild_id={message.guild.id}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,en-US;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Authorization": Authorization.get("auth")
                }

        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            try:
                json_result = response.json()
                bio = json_result.get('user', {}).get('bio')
        
                if bio:
                    log.info(f"(Bio):{bio}")
                    keywords_to_exclude = [
                '招代理', '购买', '招辅助代理', '辅助代理商', 'eseller', '中国经销',
                '中国总经销', '官方经销', '总经销', '代理', '官方总代', '诚招合作', '加盟',
                '一起赚钱', '转售菜单', '转售辅助', '中国卖家', '入代私聊', '科技代理商',' 代理', '經銷', '低價',
                'Shop', 'Cheapest', 'Store', '商业合作'
                ]
                    for keyword in keywords_to_exclude:
                        if keyword in bio:
                            muterole = message.guild.get_role(1058656520851697714)
                            ntfcn = message.guild.get_channel(970972545564168232) #通知频道-仅管理员频道
                            await message.author.add_roles(muterole, reason="[自动]个人介绍:潜在的代理或经销商")
                            await ntfcn.send(f"{message.author.mention}的个人介绍中可能存在广告行为,已被临时禁言,管理员请人工确认.\n 当前个人介绍快照:{bio} \n如需取消禁言并信任此用户的个人介绍,请输入命令:&pftrust {message.author.id}")
                            await message.author.send("您被识别为潜在的广告或垃圾账号,已被禁言,请等待管理员人工确认.")
                            break
            except ValueError:
                log.info("无法解析JSON结果。")
        else:
            log.info(f"请求失败: {response.status_code}")
            log.info(response.text)

    @commands.Cog.listener()
    async def on_message(self, message):
        author = message.author
        if message.guild is None or self.bot.user == author:
            return

        if await self.bot.cog_disabled_in_guild(self, message.guild):
            return

        valid_user = isinstance(author, discord.Member) and not author.bot
        if not valid_user:
            return

        #  Bots and mods or superior are ignored from the filter

        # As are anyone configured to be
        if await self.bot.is_automod_immune(message):
            return

        await i18n.set_contextual_locales_from_guild(self.bot, message.guild)

        deleted = await self.check_duplicates(message)

        if not deleted:
            await self.check_mention_spam(message)
            await self.muteadacc(message)

    @staticmethod
    def _update_past_names(name: str, name_list: List[Optional[str]]) -> None:
        while None in name_list:  # clean out null entries from a bug
            name_list.remove(None)
        if name in name_list:
            # Ensure order is maintained without duplicates occurring
            name_list.remove(name)
        name_list.append(name)
        while len(name_list) > 20:
            name_list.pop(0)

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User):
        if before.name != after.name:
            track_all_names = await self.config.track_all_names()
            if not track_all_names:
                return
            async with self.config.user(before).past_names() as name_list:
                self._update_past_names(before.name, name_list)
        if before.display_name != after.display_name:
            track_all_names = await self.config.track_all_names()
            if not track_all_names:
                return
            async with self.config.user(before).past_display_names() as name_list:
                self._update_past_names(before.display_name, name_list)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.nick != after.nick and before.nick is not None:
            guild = after.guild
            if (not guild) or await self.bot.cog_disabled_in_guild(self, guild):
                return
            track_all_names = await self.config.track_all_names()
            track_nicknames = await self.config.guild(guild).track_nicknames()
            if (not track_all_names) or (not track_nicknames):
                return
            async with self.config.member(before).past_nicks() as nick_list:
                self._update_past_names(before.nick, nick_list)

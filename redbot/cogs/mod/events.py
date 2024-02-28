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
import re
from PIL import Image
from pyzbar import pyzbar
import os

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
                ntfcnsec = message.guild.get_channel(1162401982649204777) #通知频道-次要-bot命令频道
                await ntfcnsec.send("Bio解析模块疑似故障")

        else:
            log.info(f"请求失败: {response.status_code}")
            log.info(response.text)

    async def check_hidelinks(self, message: discord.Message):
        guildid = message.guild.id
        if guildid != 388227343862464513:
            return

        pattern_hidelink = re.compile(r'\[([^\]]+)\]\((https?:\/\/[^\s]+)\)')
        match_hidelink = pattern_hidelink.search(message.content)
        if match_hidelink:
            await message.channel.send(f'检测到markdown语法隐藏的网址,你看到的网址并非将要访问的目标网址,真实的域名被发送者故意隐藏了! 继续访问存在潜在的诈骗风险,请在访问前再次检查此网址,不要输入任何账号密码等敏感信息,不要相信天上会掉馅饼,拒绝free nitro、steam礼金等骗局,警惕steam、discord等盗号')
            ntfcn = message.guild.get_channel(1162401982649204777) #通知频道-次要-bot命令频道
            await ntfcn.send(f"{message.author.mention}的消息中存在使用Markdown语法隐藏的网址. \n 当前消息快照:{message.content}")

    async def decodeqr(self, message: discord.Message):
        guildid = message.guild.id
        if guildid != 388227343862464513:
            return

        if message.attachments:
            ntfcn = message.guild.get_channel(1162401982649204777) #通知频道-次要-bot命令频道
            count_mk = 0
            for attachment in message.attachments:
                if attachment.filename.endswith('.png') or attachment.filename.endswith('.jpg') or attachment.filename.endswith('.jpeg'):
                    await attachment.save(f"/root/bot_tmp/atc/temp_image{message.id}_{count_mk}.png")
                    img = Image.open(f"/root/bot_tmp/atc/temp_image{message.id}_{count_mk}.png")
                    decoded_objects = pyzbar.decode(img)
            
                    if decoded_objects:
                        for obj in decoded_objects:
                            qr_code_data = obj.data.decode("utf-8")
                            if "wxp://" in qr_code_data or "qr.alipay.com" in qr_code_data:
                                await message.delete()
                                await message.channel.send("检测到微信/支付宝收款码,已撤回.本群禁止金钱交易.请勿扫码付款,存在诈骗风险.")
                                await ntfcn.send(f"{message.author.mention}的消息中存在微信/支付宝收款码. \n 二维码链接:{qr_code_data}")
                                continue
                            if "qm.qq.com" in qr_code_data or "group_code" in qr_code_data or "jq.qq.com" in qr_code_data:
                                await message.delete()
                                await message.channel.send("从二维码中识别到QQ群或个人名片信息,已撤回,未经频道主同意请勿引流! 请勿加入此QQ群或添加此人,存在诈骗风险")
                                await ntfcn.send(f"{message.author.mention}的消息中存在QQ群二维码或个人名片. \n 二维码链接:{qr_code_data}")
                                continue
                            if "weixin.qq.com/g" in qr_code_data or "u.wechat.com" in qr_code_data or "jq.qq.com" in qr_code_data:
                                await message.delete()
                                await message.channel.send("从二维码中识别到微信群或个人名片信息,已撤回,未经频道主同意请勿引流! 请勿加入此微信群或添加此人,存在诈骗风险")
                                await ntfcn.send(f"{message.author.mention}的消息中存在微信群二维码或个人名片. \n 二维码链接:{qr_code_data}")
                                continue
                            if "weixin110.qq.com" in qr_code_data:
                                await message.delete()
                                await message.channel.send("识别到疑似微信注册辅助验证二维码,已撤回! 请勿替陌生人完成微信注册或解封验证!")
                                await ntfcn.send(f"{message.author.mention}的消息中存在微信注册辅助验证二维码. \n 二维码链接:{qr_code_data}")
                                continue
                            if "discord.com/ra/" in qr_code_data:
                                await message.delete()
                                await message.channel.send("识别到疑似Discord登录二维码,已撤回! 请勿扫码付款,存在盗号风险!")
                                await ntfcn.send(f"{message.author.mention}的消息中存在疑似Discord登录二维码. \n 二维码链接:{qr_code_data}")
                                continue
                            await message.channel.send(f"检测到二维码,已完成内容识别：{qr_code_data}")
                    img.close()
                    os.remove(f"/root/bot_tmp/atc/temp_image{message.id}_{count_mk}.png")        
                count_mk += 1

    async def checkurl(self, message: discord.Message):
        guildid = message.guild.id
        if guildid != 388227343862464513:
            return
        ntfcn = message.guild.get_channel(1162401982649204777) #通知频道-次要-bot命令频道

        if "weixin110.qq.com" in message.content or "weixin.qq.com/g" in message.content or "u.wechat.com" in message.content or "jq.qq.com" in message.content or "qm.qq.com" in message.content or "group_code" in message.content or "qr.alipay.com" in message.content or "wxp://" in message.content or "/t.me/" in message.content or "discord.com/ra/" in message.content:
            if "t.me" in message.content and "GTA5OnlineToolsPornVideo" in message.content:
                return
            await message.delete()
            await message.channel.send("检测可疑的链接,已撤回!")
            await ntfcn.send(f"{message.author.mention}的消息中存在可疑链接(收付款/个人或群名片/微信辅助验证/discord登录). \n 当前消息快照:{message.content}")
            return
            
        
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
            await self.check_hidelinks(message)
            await self.decodeqr(message)
            await self.checkurl(message)
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

import datetime
import logging
from collections import defaultdict, deque
from typing import List, Optional
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
import asyncio
import tldextract
import multiprocessing
import time
import threading

_ = i18n.Translator("Mod", __file__)
log = logging.getLogger("red.mod")


class Events(MixinMeta):
    """
    This is a mixin for the core mod cog
    Has a bunch of things split off to here.
    """
    async def repeattosoftban(self, guild, author, channel, member, reason):
        guild = guild
        author = author

        if author == member:
            log.info("cannot selfban")
            return

        audit_reason = get_audit_reason(author, reason, shorten=True)

        try:  # We don't want blocked DMs preventing us from banning
            if guild.id == 388227343862464513:
                invitelink = "https://discord.gg/7GuNzajfhD"
            else:
                invitelink = await channel.create_invite(max_uses=1)
                invitelink = invitelink.url
            msg = await member.send(
                _(
                    "你已被踢出,最近一天的消息已被删除.\n"
                    "您的账号被Bugbot判定为广告机器人账号，判定原因: {banreson}\n"
                    "如果您对自己在此群组发送消息这件事完全不知情,那么您的Discord账号已经被黑客控制\n"
                    "请检查账号状态并修改密码以排除盗号隐患.之后你可以通过此链接重新加入server. {invitelink}"
                ).format(invitelink=invitelink, banreson=reason),
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
                datetime.datetime.now(),
                "softban",
                member,
                author,
                reason,
                until=None,
                channel=None,
            )


    async def check_duplicates(self, message):
        
        guild = message.guild
        author = message.author
        channel=message.channel
        guild_cache = self.cache.get(guild.id, None)
        if guild_cache is None:
            repeats = await self.config.guild(guild).delete_repeats()
            if repeats == -1:
                return False
            guild_cache = self.cache[guild.id] = defaultdict(lambda: deque(maxlen=6))
        
        if not message.content:
            return False
            # Off-topic # 频道公告 # mod-only # 规则
        if channel.id == 976462395427921940 or channel.id == 608168595314180106 or channel.id == 970972545564168232 or channel.id == 877000289146798151:
        
            return False

        guild_cache[author].append(message.content)
        msgs = guild_cache[author]
        # log.info(f"msgslen:{len(msgs)} setmsgslen:{len(set(msgs))}")
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
        if len(msgs) == 6 and len(set(msgs)) == 2:
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
            mod_cache = self.cache_mod.get(guild.id, None)
            if mod_cache is None:
                mod_cache = self.cache_mod[guild.id] = defaultdict(lambda: deque(maxlen=6))
            modmsgs = mod_cache[message.author]
            if len(modmsgs) > 0:
                log.info(f"限速锁定未解除锁定 {len(modmsgs)}")
                await message.delete()
                return False
                
            mod_cache[message.author].append("locked")
            msgs.clear()
            try:
                until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=10)
                await author.edit(timed_out_until=until, reason="[自动]softban预处理")
            except discord.HTTPException:
                mod_cache[author].clear()
                pass
            try:
                ysch = self.bot.get_user(1044589526116470844)
                await self.repeattosoftban(guild, ysch, channel, author, "[自动]连续发送六条内容相同的消息")
                if guild.id == 388227343862464513:
                    ntfcn = message.guild.get_channel(970972545564168232) #通知频道-仅管理员频道
                    await ntfcn.send(f"<@{author.id}>  ({message.author.nick}) 被识别为广告机,已撤回近24h消息并踢出.\n判断原因:连续发送六条内容相同的消息\n最近一条消息为```{message.content}```")
                
                log.warning(
                        "已移除用户 ({member}) 在 {guild}".format(
                            member=author.id, guild=guild.id
                        )
                    )
                mod_cache[author].clear()
                return True
            except discord.HTTPException:
                mod_cache[author].clear()
                pass

        return False
    
    async def ckeck_automod_content(self, execution):
        guild = execution.guild
        author = execution.member
        if not "discord" in execution.content:
            return False
        if execution.action.type == discord.AutoModRuleActionType.send_alert_message:
            return False
        
        mod_cache = self.cache_mod.get(guild.id, None)

        if mod_cache is None:
            mod_cache = self.cache_mod[guild.id] = defaultdict(lambda: deque(maxlen=6))
            
        modmsgs = mod_cache[author]
        if len(modmsgs) > 0:
            log.info(f"限速锁定未解除锁定 {len(modmsgs)}")
            return False
        if "@everyone" in execution.content or "@here" in execution.content or "nude" in execution.content or "Onlyfans" in execution.content or "Teen" in execution.content or "leak" in execution.content or "Leak" in execution.content or "porn" in execution.content:
            mod_cache[author].append(execution.content)
            log.info(f"限速锁定已锁定 {len(modmsgs)}")

            try:
                until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=10)
                await author.edit(timed_out_until=until, reason="[自动]softban预处理")
            except discord.HTTPException:
                pass
            if guild.id != 388227343862464513:
                mod_cache[author].clear()
                log.info(f"限速锁定解除 {len(modmsgs)}")

                return False

            try:
                ysch = self.bot.get_user(1044589526116470844)
                invitechannel = guild.get_channel(605035182143176711)
                modchannel = guild.get_channel(970972545564168232)
                await modchannel.send(f"解析Automod动作+关键词检测: 已踢出 <@{author.id}> 并通知其修改密码.")
                await self.repeattosoftban(guild, ysch, invitechannel, author, "[自动]同时触发Doscord Automod+关键词黑名单识别")
                mod_cache[author].clear()
                log.info(f"限速锁定解除 {len(modmsgs)}")

                log.warning(
                        "已移除用户 ({member}) 在 {guild}".format(
                            member=author.id, guild=guild.id
                        )
                    )
                return True
            except discord.HTTPException:
                pass



    async def check_duplicates_automod(self, execution):
        guild = execution.guild
        if guild.id != 388227343862464513:
            return False
        if execution.action.type == discord.AutoModRuleActionType.send_alert_message:
            return False
        author = execution.member

        mod_cache = self.cache_mod.get(guild.id, None)
        if mod_cache is None:
            mod_cache = self.cache_mod[guild.id] = defaultdict(lambda: deque(maxlen=6))
        modmsgs = mod_cache[author]
        if len(modmsgs) > 0:
            log.info(f"限速锁定未解除锁定 {len(modmsgs)}")
            return False

        guild_cache = self.cache.get(guild.id, None)
        if guild_cache is None:
            repeats = await self.config.guild(guild).delete_repeats()
            if repeats == -1:
                return False
            guild_cache = self.cache[guild.id] = defaultdict(lambda: deque(maxlen=7))
        
        if not execution.content:
            return False
        
        guild_cache[author].append(execution.content)
        msgs = guild_cache[author]

        if len(msgs) == 3 and len(set(msgs)) == 1:
            mod_cache[author].append("locked")

            try:
                msgs.clear()
                until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=10)
                await author.edit(timed_out_until=until, reason="[自动]softban预处理")
            except discord.HTTPException:
                mod_cache[author].clear()
                pass
            try:
                ysch = self.bot.get_user(1044589526116470844)
                invitechannel = guild.get_channel(605035182143176711)
                modchannel = guild.get_channel(970972545564168232)
                await modchannel.send(f"解析Automod动作: 已踢出 <@{author.id}> 并通知其修改密码.")
                await self.repeattosoftban(guild, ysch, invitechannel, author, "[自动]累计三次触发Discord Automod关键词拦截")
                log.info(f"限速锁定解除 {len(modmsgs)}")
                mod_cache[author].clear()

                log.warning(
                        "已移除用户 ({member}) 在 {guild}".format(
                            member=author.id, guild=guild.id
                        )
                    )
                return True
            except discord.HTTPException:
                mod_cache[author].clear()
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
                    keywords_to_include = [
                '招代理', '购买', '招辅助代理', '辅助代理商', 'reseller','Reseller', '中国经销',
                '中国总经销', '官方经销', '总经销', '代理', '官方总代', '诚招合作', '加盟','誠信',
                '一起赚钱', '转售菜单', '转售辅助', '中国卖家', '入代私聊', '科技代理商',' 代理', '經銷', '低價', 'gta5辅助', 'gta5菜单', 'gta5外挂', 'gta5模组', 'gta辅助', 'gta菜单', 'gta外挂', 'gta模组', '卖gta', '销售', 'Gta5辅助', 'Gta5菜单', 'Gta5外挂', 'Gta5模组', 'Gta辅助', 'Gta菜单', 'Gta外挂', 'Gta模组', '卖Gta', 'GTA5辅助', 'GTA5菜单', 'GTA5外挂', 'GTA5模组', 'GTA辅助', 'GTA菜单', 'GTA外挂', 'GTA模组', '卖GTA'
                'Shop', 'Cheapest', 'Store','shop', 'cheapest', 'store', '商业合作', 'Titan', 'Erebus', 'discord.gg', 'discord.com'
                ]
                    for keyword in keywords_to_include:
                        if keyword in bio:
                            muterole = message.guild.get_role(1058656520851697714)
                            await message.author.add_roles(muterole, reason="[自动]个人介绍:潜在的代理或经销商")
                            if guildid == 388227343862464513:
                                ntfcn = message.guild.get_channel(970972545564168232) #通知频道-仅管理员频道
                                await ntfcn.send(f"{message.author.mention}的个人介绍中可能存在广告行为,已被临时禁言,管理员请人工确认.\n 当前个人介绍快照:```{bio}``` \n如需取消禁言并信任此用户的个人介绍,请输入命令:```&pftrust {message.author.id}```")
                            try:
                                await message.author.send("经过对用户名/个人简介/消息的评估,您被识别为潜在的广告或垃圾账号,已被禁言,请等待管理员人工确认.如果您是付费菜单的经销商,我们默认您不需要在小助手群组中寻求帮助,为防止间接的广告行为,您可以继续浏览消息,但不再能够发送消息或添加反应.若您的业务范围不包含付费辅助或成人内容,通常经过人工审核后将解除禁言.")
                            except discord.HTTPException:
                                pass
                            await message.delete()
                            break
            except ValueError:
                log.info("BIO-无法解析JSON结果。")
                ntfcnsec = message.guild.get_channel(1162401982649204777) #通知频道-次要-bot命令频道
                await ntfcnsec.send("Bio解析模块疑似故障-json解析失败")

        else:
            log.info(f"BIO请求失败: {response.status_code}")
            log.info(response.text)
            ntfcnsec = message.guild.get_channel(1162401982649204777) #通知频道-次要-bot命令频道
            await ntfcnsec.send(f"Bio解析模块疑似故障-HTTP ERROR:{response.status_code}")


    async def check_hidelinks(self, message: discord.Message):
        guildid = message.guild.id

        pattern_hidelink = re.compile(r'\[([^\]]+)\]\((https?:\/\/[^\s]+) ?\)')
        match_hidelink = pattern_hidelink.search(message.content)
        if match_hidelink:
            relurlpattern = r"(https?://\S+)"
            scanedurls = re.findall(relurlpattern, message.content)
            for surl in scanedurls:
                domainpre = tldextract.extract(surl).domain
                suffix = tldextract.extract(surl).suffix
                domain = domainpre + "." + suffix
                if domain == "discordapp.com":
                    return
                
            if "steamcommunity.com/gift" or "from steam" in message.content:
                mod_cache = self.cache_mod.get(guildid, None)
                if mod_cache is None:
                    mod_cache = self.cache_mod[guildid] = defaultdict(lambda: deque(maxlen=6))
                modmsgs = mod_cache[message.author]
                if len(modmsgs) > 0:
                    log.info(f"限速锁定未解除锁定 {len(modmsgs)}")
                    await message.delete()
                    return False
                
                mod_cache[message.author].append("locked")
                try:
                    until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=30)
                    await message.author.edit(timed_out_until=until, reason="[自动]softban预处理")
                    await message.channel.send(f"{message.author.mention} 被判定为广告机(steam礼品卡诈骗),已踢出.天上没有馅饼,推广免费礼物、nitro、18+内容的均为诈骗.勿填写勿扫码.")
                    ysch = self.bot.get_user(1044589526116470844)
                    await self.repeattosoftban(message.guild, ysch, message.channel, message.author, "[自动]发送盗号链接(steam礼品卡)")
                    if guildid == 388227343862464513:
                        ntfcn = message.guild.get_channel(970972545564168232) #通知频道-仅管理员频道
                        await ntfcn.send(f"<@{message.author.id}>  ({message.author.nick}) 被识别为广告机,已撤回近24h消息并踢出.\n判断原因:steam礼品卡诈骗链接\n当前消息快照:```{message.content}```")

                except discord.HTTPException:
                    pass
                log.info(f"限速锁定解除 {len(modmsgs)}")
                mod_cache[message.author].clear()
                return True

            await message.delete()
            await message.channel.send(f'{message.author.mention} 请勿使用markdown语法隐藏真实网址,原始消息已私发给您,请重新编辑', delete_after=60)
            try:
                await message.author.send(f"请勿使用markdown语法隐藏真实网址,请重新编辑.您的原始消息内容: ```{message.content}```")
            except discord.HTTPException:
                pass
            if guildid == 388227343862464513:
                ntfcn = message.guild.get_channel(1162401982649204777) #通知频道-次要-bot命令频道
                await ntfcn.send(f"{message.author.mention} ({message.author.nick}) 的消息中存在使用Markdown语法隐藏的网址. \n 当前消息快照:```{message.content}```")
            return True
        return False

    async def decodeqr(self, message: discord.Message):
        guildid = message.guild.id
        if guildid != 388227343862464513:
            return

        if message.attachments:
            ntfcn = message.guild.get_channel(1162401982649204777) #通知频道-次要-bot命令频道
            count_mk = 0
            for attachment in message.attachments:
                if attachment.filename.endswith('.png') or attachment.filename.endswith('.jpg') or attachment.filename.endswith('.jpeg'):
                    await attachment.save(f"/home/sch/bot_tmp/atc/temp_image{message.id}_{count_mk}.png")
                    img = Image.open(f"/home/sch/bot_tmp/atc/temp_image{message.id}_{count_mk}.png")
                    decoded_objects = pyzbar.decode(img)
            
                    if decoded_objects:
                        for obj in decoded_objects:
                            qr_code_data = obj.data.decode("utf-8")
                            if qr_code_data == "":
                                continue 
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
                            await message.channel.send(f"检测到二维码,已完成内容识别：{qr_code_data} 警告：正常聊天不需要用到二维码。二维码通常用于隐藏网址。为保护您的个人利益，规避隐私和法律风险，请勿分享登录信息或帮助验证。发送存在登录或验证二维码者请主动撤回。否则将被禁言！")
                    img.close()
                    os.remove(f"/home/sch/bot_tmp/atc/temp_image{message.id}_{count_mk}.png")        
                count_mk += 1

    async def checkurl(self, message: discord.Message):
        guildid = message.guild.id

        if "weixin110.qq.com" in message.content or "weixin.qq.com/g" in message.content or "u.wechat.com" in message.content or "jq.qq.com" in message.content or "qm.qq.com" in message.content or "group_code" in message.content or "qr.alipay.com" in message.content or "wxp://" in message.content or "discord.com/ra/" in message.content:
            await message.delete()
            await message.channel.send("检测可疑的链接,已撤回!")
            if guildid == 388227343862464513:
                ntfcn = message.guild.get_channel(1162401982649204777) #通知频道-次要-bot命令频道
                await ntfcn.send(f"{message.author.mention}的消息中存在可疑链接(收付款/个人或群名片/微信辅助验证/discord登录). \n 当前消息快照:```{message.content}```")
            return True
        return False
    
    async def VT_file_scan(self, file_path, message: discord.Message):
        VT_key = await self.bot.get_shared_api_tokens("virustotal")
        if VT_key.get("apikey") is None:
            return
        url = 'https://www.virustotal.com/api/v3/files'
        headers = {'x-apikey': VT_key.get("apikey")}
        with open(file_path, 'rb') as file_f:
            response = requests.post(url, files={'file': file_f}, headers=headers)
        os.remove(file_path)
        if response.status_code == 200:
            json_response = response.json()

            data = json_response['data']
            aid = data['id']

            url = f'https://www.virustotal.com/api/v3/analyses/{aid}'
            headers = {'x-apikey': VT_key.get("apikey")}

            thread2 = threading.Thread(target=self.call_async_VT_file_scan, args=(url, message))
            thread2.start()
        return

    
    def call_async_VT_url_scan(self, susurl, message: discord.Message):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.VT_url_scan(susurl, message))

    def call_async_VT_file_scan(self, surl, message: discord.Message):
        loop2 = asyncio.new_event_loop()
        asyncio.set_event_loop(loop2)
        loop2.run_until_complete(self.VT_file_scan_rlt(surl, message))

    async def VT_file_scan_rlt(self, url, message: discord.Message,):
            VT_key = await self.bot.get_shared_api_tokens("virustotal")
            if VT_key.get("apikey") is None:
                return
            headers = {'x-apikey': VT_key.get("apikey")}

            i = 30
            while i > 0:
                i = i - 1
                response2 = requests.get(url, headers=headers)
                
                if response2.status_code == 200:
                    json_response2 = response2.json()
                    statusdata = json_response2['data']['attributes']['status']
                    if statusdata == 'completed':
                        break
                await asyncio.sleep(15)
            if i <= 0:
                return
            
            analysdata = json_response2['data']
            harmc = analysdata['attributes']['stats']['malicious']
            susc = analysdata['attributes']['stats']['suspicious']
            noharmc = analysdata['attributes']['stats']['harmless']
            if harmc > 0 or susc > 0:
                bot_key = await self.bot.get_shared_api_tokens("bugbot")
                if bot_key.get("api_key") is None:
                    return
                restapi_sendmsg = f'https://discord.com/api/v9/channels/{message.channel.id}/messages'

                data = {
                    'content': str(f'{message.author.mention}的消息中存在可疑文件,经VirusTotal在线查毒, {harmc} 个引擎标记为病毒, {susc} 个引擎标记为可疑, {noharmc} 个引擎未检出异常. 结果仅供参考.'),
                }

                headers = {
                    'Authorization': f'Bot {bot_key.get("api_key")}',
                    'Content-Type': 'application/json',
                }        
                httprlt = requests.post(restapi_sendmsg, json=data, headers=headers)
            return
            

    async def VT_url_scan(self, susurl, message: discord.Message):

        VT_key = await self.bot.get_shared_api_tokens("virustotal")
        if VT_key.get("apikey") is None:
            return
        url = 'https://www.virustotal.com/api/v3/urls'
        query_params = {'url': susurl}
        headers = {'x-apikey': VT_key.get("apikey")}

        response = requests.post(url, params=query_params, headers=headers)
        if response.status_code == 200:
            json_response = response.json()

            data = json_response['data']
            aid = data['id']

            url = f'https://www.virustotal.com/api/v3/analyses/{aid}'
            headers = {'x-apikey': VT_key.get("apikey")}
            i = 5
            while i > 0:

                i = i - 1
                response2 = requests.get(url, headers=headers)

                if response2.status_code == 200:
                    json_response2 = response2.json()
                    statusdata = json_response2['data']['attributes']['status']
                    if statusdata == 'completed':
                        break

                await asyncio.sleep(15)
            
            if i <= 0:
                return
            
            analysdata = json_response2['data']
            harmc = analysdata['attributes']['stats']['malicious']
            susc = analysdata['attributes']['stats']['suspicious']
            noharmc = analysdata['attributes']['stats']['harmless']
            if harmc > 0 or susc > 0:            
                bot_key = await self.bot.get_shared_api_tokens("bugbot")
                if bot_key.get("api_key") is None:
                    return
                restapi_sendmsg = f'https://discord.com/api/v9/channels/{message.channel.id}/messages'

                data = {
                    'content': str(f'{message.author.mention}的消息中存在可疑链接,经VirusTotal在线查毒, {harmc} 个引擎标记为病毒, {susc} 个引擎标记为可疑, {noharmc} 个引擎未检出异常. 结果仅供参考.'),
                }

                headers = {
                    'Authorization': f'Bot {bot_key.get("api_key")}',
                    'Content-Type': 'application/json',
                }        
                requests.post(restapi_sendmsg, json=data, headers=headers)
        return


    async def filesafecheck(self, message: discord.Message):
            if len(message.attachments) > 0:
                for attachment in message.attachments:
                    file_path = f'/home/sch/bot_tmp/atc/{attachment.filename}'
                    if attachment.content_type == None:
                        return
                    if attachment.content_type.startswith("image") or attachment.content_type.startswith("text") or attachment.content_type.startswith("audio") or attachment.content_type.startswith("video"):
                        return
                    await attachment.save(file_path)
                    if os.path.getsize(file_path) > 30 * 1024 * 1024:
                        os.remove(file_path)
                        return
            
                    await self.VT_file_scan(file_path, message)
    
    async def urlsafecheck(self, message: discord.Message):
                content = message.content
                urlpattern = r"(https?://\S+)"
                urls = re.findall(urlpattern, content)
                for url in urls:
                    if url.startswith("https://t.me/GTA5OnlineToolsPornVideo/"):
                        continue
                    domainpre = tldextract.extract(url).domain
                    suffix = tldextract.extract(url).suffix
                    domain = domainpre + "." + suffix
                    if domain == "github.com" or domain == "youtube.com" or domain == "youtu.be" or domain == "bilibili.com" or domain == "b23.tv" or domain == "githubusercontent.com" or domain == "discord.com" or domain == "discord.gg" or domain == "123pan.com" or domain == "host3650.live" or domain == "microsoft.com" or domain == "unknowncheats" or domain == "wikipedia.org" or domain == "vxtwitter.com" or domain == "twitter.com" or domain == "x.com" or domain == "crazyzhang.cn" or domain == "discordapp.com":
                        continue
                    thread1 = threading.Thread(target=self.call_async_VT_url_scan, args=(url, message))
                    thread1.start()

    async def check_ping_everyone_here(self, message: discord.Message):
        if "@everyone" in message.content or "@here" in message.content:
            await message.delete()
            await message.channel.send(f'{message.author.mention} 您不具有ping everyone or here权限.', delete_after=60)
            if message.guild.id == 388227343862464513:
                ntfcn = message.guild.get_channel(1162401982649204777) #通知频道-次要-bot命令频道
                await ntfcn.send(f"{message.author.mention}试图mention everyone or here. \n 当前消息快照:```{message.content}```")
            try:
                await message.author.send(f"您的原始消息是: ```{message.content}```")
            except discord.HTTPException:
                pass
            return True

    @commands.Cog.listener()
    async def on_automod_action(self, execution):
        detected = await self.check_duplicates_automod(execution)
        if not detected:
            await self.ckeck_automod_content(execution)
 
    @commands.Cog.listener()
    async def on_message_edit(self, _prior, message):
        await self.on_message(message)

    @commands.Cog.listener()
    async def on_message(self, message):
        author = message.author
        if message.guild is None or self.bot.user == author:
            return

        if await self.bot.cog_disabled_in_guild(self, message.guild):
            return
        
        if message.channel.id == 970972545564168232: #绕过mod-only
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
            deleted = await self.check_hidelinks(message)
            if not deleted:
                deleted = await self.check_ping_everyone_here(message)
                if not deleted:
                    # await self.decodeqr(message)
                    deleted = await self.checkurl(message)
                    if not deleted:
                        await self.urlsafecheck(message)
                        await self.filesafecheck(message)

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

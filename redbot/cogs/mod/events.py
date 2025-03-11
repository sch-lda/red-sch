import datetime
import json
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
import aiohttp

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

    def isonlycontainsemoji(self, content):
        emoji_pattern = r'<:.*?:\d+>'
        traditional_emoji_pattern = re.compile(r'[\U0001F600-\U0001F64F]')
        traditional_emoji = re.findall(traditional_emoji_pattern, content)
        emojis = re.findall(emoji_pattern, content)
        all_emojis = traditional_emoji + emojis
        if len(all_emojis) == len(content):
            return True
        return False
    
    async def fetch_forwards(self, message):
        reference = message.reference
        if reference is not None:
            ref_channel = self.bot.get_channel(reference.channel_id)
            if ref_channel is None:
                await message.delete()
                await message.channel.send(f"<@{message.author.id}>.Discord ID:({message.author.id}),检测到bot无权限读取的内容，可能是来自私聊或其他服务器的消息，已删除.")
                log.info(f"转发消息获取失败: {message}")
                return None
            if ref_channel.guild.id != message.guild.id:
                await message.delete()
                await message.channel.send(f"<@{message.author.id}>.Discord ID:({message.author.id}),检测到bot无权限读取的内容，可能是来自私聊或其他服务器的消息，已删除.")
                return None
            ref_msg = await ref_channel.fetch_message(reference.message_id)
            if ref_msg is not None:
                return ref_msg
            else:
                log.info(f"转发消息获取失败: {message}")
                return None
        else:
            log.info(f"转发消息获取失败: {message}")
            return None
        return None
        
    async def check_duplicates(self, message):
        
        guild = message.guild
        author = message.author
        channel = message.channel
        guild_cache = self.cache.get(guild.id, None)
        if guild_cache is None:
            repeats = await self.config.guild(guild).delete_repeats()
            if repeats == -1:
                return True
            guild_cache = self.cache[guild.id] = defaultdict(lambda: deque(maxlen=6))
        
        if message.flags.value == 16384: # 是否是转发消息
            ref_msg = await self.fetch_forwards(message)
            if ref_msg is None:
                return False
            message_content = ref_msg.content
        else:
            message_content = message.content

        if not message_content:
            return False
            # Off-topic # 频道公告 # mod-only # 规则
        if channel.id == 608168595314180106 or channel.id == 970972545564168232 or channel.id == 877000289146798151:
        
            return False

        guild_cache[author].append(message_content)
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
                    await ntfcn.send(f"<@{author.id}>  ({message.author.name}) 被识别为广告机,已撤回近24h消息并踢出.\n判断原因:连续发送六条内容相同的消息\n最近一条消息为```{message.content}```")
                
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
        
        if execution.action.type == discord.AutoModRuleActionType.send_alert_message:
            return False
        
        mod_cache = self.cache_mod.get(guild.id, None)

        if mod_cache is None:
            mod_cache = self.cache_mod[guild.id] = defaultdict(lambda: deque(maxlen=6))
            
        modmsgs = mod_cache[author]
        if len(modmsgs) > 0:
            log.info(f"限速锁定未解除锁定 {len(modmsgs)}")
            return False
        with open('/home/azureuser/.local/share/Red-DiscordBot/data/sch/cogs/Mod/automod_keywords.json', 'r', encoding='utf-8') as file:
            data = json.load(file)
        automod_keywords = data['keywords_to_include']

        if not execution.content:
            return False
        if automod_keywords is None:
            return False
        
        for keyword in automod_keywords:
            
            if keyword.lower() in execution.content.lower():

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
                    await self.repeattosoftban(guild, ysch, invitechannel, author, "[自动]同时触发Discord Automod+关键词黑名单识别")
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
                    
        return False


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

    async def affcodecheck(self, message):
        isenabled = await self.config.guild(message.guild).affcheck()
        if not isenabled:
            return False

        if message.flags.value == 16384: # 是否是转发消息
            ref_msg = await self.fetch_forwards(message)
            if ref_msg is None:
                return False
            message_content = ref_msg.content
        else:
            message_content = message.content

        guild, author = message.guild, message.author
        detect_list = ["affcode","register?code","guest/i","invite_code","?register=","?aff=","utm_content"]

        for aff in detect_list:
            if aff in message_content:
                await message.reply("检测到包含邀请参数的链接.链接所有者可能会从中获得邀请报酬,包括但不限于充值分成.机场的分享者应在说明后发送带邀请参数的链接,其他人应享有知情权,自愿参与.机场或服务的任何问题(信息泄露、跑路)与本server无关,无人能够担保,请自行甄别.\n如果您频繁发送或者在无人询问的情况下主动推广机场等付费资源,您将被警告甚至禁言.")

    async def autorole(self, message):
        isenabled = await self.config.guild(message.guild).autobaserole()
        if not isenabled:
            return False
        guild, author = message.guild, message.author
        if guild.id != 388227343862464513:
            return
        if message.channel.id == 608951880403517470:
            return
        if message.channel.id == 1254956902308122664:
            return

        if author.bot:
            return
        
        #rolebasic = guild.get_role(970624921514410064) #小航海
        #roleadvanced = guild.get_role(605240349459349511) #大航海
        #roleAdmin = guild.get_role(753452989527752704) #Admin
        #roleSupperAdmin = guild.get_role(727043477816475748) #管理员
        #roleLuaDEV = guild.get_role(999296419288600666) #Lua开发
        #roleOwner = guild.get_role(606112096354172928) #舰长
        #roleMod = guild.get_role(993016334730395801) #moderator

        allroleids = [970624921514410064,605240349459349511,753452989527752704,727043477816475748,999296419288600666,606112096354172928, 993016334730395801]

        roles = author.roles
        userroleids = [role.id for role in roles]

        for roleid in allroleids:
            if roleid in userroleids:
                return
            
        rolebasic = guild.get_role(970624921514410064) #小航海
        await author.add_roles(rolebasic)
        await message.channel.send(f"{author.mention} 您没有任何身份组,已为您分配小航海组.")

    async def openai_request(self, modelstr, userprompt, sysprompt) -> Optional[str]:

        try:
            openai_api_key = await self.bot.get_shared_api_tokens("openai")
            if openai_api_key.get("api_key") is None:
                log.info("OpenAI API Key 未设置")
                return None
            
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {openai_api_key.get("api_key")}'
            }

            data = {
                "model": modelstr,
                "messages": [
                    {
                        "role": "system",
                        "content": sysprompt
                    },
                    {
                        "role": "user",
                        "content": userprompt
                    }
                ]
            }

            # 发送请求到 OpenAI API
            async with aiohttp.ClientSession() as session:
                async with session.post('https://gptoneapi.cc2077.site/v1/chat/completions', headers=headers, json=data) as response:
                    if response.status == 200:
                        result = await response.json()
                        response_text = result['choices'][0]['message']['content'].strip()
                        return response_text
                    else:
                        log.info(f"{modelstr} 请求失败: {response}")
                        return None
                    
        except Exception as e:
            return None

    async def openaicheck(self, message):
        guild, author = message.guild, message.author
        isenabled = await self.config.guild(message.guild).aicheck()
        if not isenabled:
            return False

        # if guild.id != 1056808446030250044:
        #     return
        if message.channel.id == 608951880403517470:
            return
        if self.isonlycontainsemoji(message.content):
            return

        if message.flags.value == 16384: # 是否是转发消息
            ref_msg = await self.fetch_forwards(message)
            if ref_msg is None:
                return
            message_content = ref_msg.content
        else:
            message_content = message.content
        
        channel = message.channel
        if channel.id == 703228036157538364:
            return
        
        current_time = datetime.datetime.now(datetime.timezone.utc)
        last_check = await self.config.member_from_ids(guild.id, author.id).msg_last_check_time()
        if last_check != "":
            last_check_f = datetime.datetime.fromisoformat(last_check)
            if current_time - last_check_f < datetime.timedelta(minutes=5) and author.id != 1090151704776933417:
                # log.info(f"跳过对用户 {userid} 的msg检查,下次检查时间: {last_check_f + datetime.timedelta(hours=6)}")
                return
        
        openai_api_key = await self.bot.get_shared_api_tokens("openai")
        if openai_api_key.get("api_key") is None:
            return
        with open('/home/azureuser/.local/share/Red-DiscordBot/data/sch/cogs/Mod/ad_keywords.txt', 'r', encoding='utf-8') as file:
            ad_keywords = [line.strip() for line in file.readlines()]

        guild_cache = self.cache_aicheck.get(guild.id, None)
        if guild_cache is None:
            repeats = await self.config.guild(guild).delete_repeats()
            if repeats == -1:
                return True
            guild_cache = self.cache_aicheck[guild.id] = defaultdict(lambda: deque(maxlen=10))
        
        guild_cache[author].append(message_content)

        last_ten_msgs = list(guild_cache[author])
        
        ad_keywords_string = ", ".join(ad_keywords)
        # prompt = f"你是一个语义分析助手,对输入的聊天消息进行分析,如果满足任意条件,返回yes,否则返回no.条件1:消息涉及对中国(包含港澳台)政治问题的讨论.条件2:包含对其他聊天者的严重的侮辱.条件3:涉及社工库(人肉搜索/开盒)等泄露个人敏感信息.条件4:加密货币宣传或诈骗.条件5:消息大意与给出的广告语义库(括号内的为注释)中的任一项相符.讨论或询问标注为P2C菜单名的软件都视为广告,注意区分stand/alpha等词作普通英文单词还是作软件名\n广告语义库: {ad_keywords_string}\n聊天消息: {message.content}"
        system_prompt = """Role: 敏感内容分析专家
            Objective: 基于语义检测消息是否符合预设风险条件
            Capability: 
            - 上下文综合分析能力
            - 消息拆分反审查识别能力
            Output:
            - 严格仅输出小写英文 yes/no
            - yes触发条件: 
            1. 政治敏感话题：包含中国及港澳台政治讨论/负面内容
            2. 危险行为：社工信息(telegram社工机器人、开盒)、加密货币推广
            3. 广告关联：匹配广告语义库关键词
                只要讨论或询问标注为P2C菜单名的软件都视为广告
            4. 拆分规避检测行为
            5. 钓鱼网站(例如把steamcommunity.com写成steamcomuunity.com的地址)
            - no触发条件: 
            所有中性/安全内容"""

        user_prompt = f"""
            当前广告关键词库：
            {ad_keywords_string}

            请严格按以下流程执行：
            1. 提取消息核心语义要素
            2. 交叉验证上下文关联性
            3. 比对所有风险维度
            4. 最终判定：<answer>
            注意，聊天消息来自侠盗猎车手游戏交流群，可能包含“抢劫”等游戏内暴力内容，不应触发风险判定。
            
            待分析消息：
            {message_content}

            上下文支持材料：
             历史消息数组(分析拆分规避行为)：
            {last_ten_msgs}

            参考示例：
            1. 厄里斯给词汇崩掉了 yes
            2. 香港有什么知名旅游景点 no
            3. GTA赌场豪劫怎么打 no
            4. 请问哪个付费菜单好用 yes
            5. erebus怎么用 yes
            6. 现在增强版什么菜单能用 no
            7. 现在增强版什么付费菜单能用 yes
            8. 大助手在哪下载 no
            9. 现在大助手能用吗 no
            10. Yim一个免费菜单，到他手里改了点东西，换了个名字，就开始拿去出售了，没点脸 no
            11. 复制整段内容，打开最新版「夸克APP」即可获取。畅享原画，免费5倍速播放，支持AI字幕和投屏，更有网盘TV版。链接：https://pan.quark.cn/s/* no
            12. 别玩虚幻5了 来一起探讨菜单 no
            13. 小助手哪里下载 no
            14. 大陆现在也注册不了谷歌了 no
            15. 大佬什么时候discord选几个人来测试一下菜单啊？我这种菜狗写不来驱动，不会内核注入 no
            16. 极度正确的政治 no
            17. 议员，给我一分钟。我要说的是，关于荔枝角收押所重建，55亿的预算加上410个床位，每个床位花费50万，这是否合理？ no
            18. https://github.com/Deadlineem/Chronix 有新菜单？ no
            19. 没同步吧，内地版的好像被阉割了很多功能 no


            """

        if len(user_prompt) > 64000:
            user_prompt = user_prompt[:64000]

        # log.info(f"user_prompt: {user_prompt}")
        
        for attempt in range(3):
            modelstr = "deepseek-v3"
            if attempt == 2:
                modelstr = "gpt-4o-mini"
            response = await self.openai_request(modelstr, user_prompt, system_prompt)
            if response is None:
                log.info(f"gpt请求失败-失败次数{attempt + 1}")
                continue
            try:
                lowerstr = response.lower()
            except:
                log.info(f"gpt请求失败-失败次数{attempt + 1}")
                continue
            if not "yes" in lowerstr and not "no" in lowerstr:
                log.info(f"gpt请求失败-失败次数{attempt + 1}")
                continue
            break
        else:
            log.info("gpt请求失败")
            return False
        
        scan_times = await self.config.guild(guild).gpt_scan_msg_count()
        scan_times += 1
        await self.config.guild(guild).gpt_scan_msg_count.set(scan_times)

        if "yes" in response.lower():
            attempt2 = 0
            recheck = "no"

            for attempt2 in range(3):
                response2 = await self.openai_request("mistral-large-latest", user_prompt, system_prompt)
                if response2 is None:
                    log.info(f"mistral请求失败-失败次数{attempt2 + 1}")
                    continue
                try:
                    lowerstr2 = response2.lower()
                except:
                    log.info(f"mistral请求失败-失败次数{attempt2 + 1}")
                    continue
                if not "yes" in lowerstr2 and not "no" in lowerstr2:
                    log.info(f"mistral请求失败-失败次数{attempt2 + 1}")
                    recheck = "yes"
                    continue
                else:
                    recheck = lowerstr2
                    break
            else:
                log.info("mistral请求失败")

            log.info(f"mistral检查结果: {lowerstr2}")

            if not "yes" in recheck:
                await message.channel.send(f"[测试阶段|语义分析] {author.mention} 的消息被归类为广告/诈骗/政治敏感/冒犯/隐私泄露,此结果未通过复核,仅供参考", delete_after=3600)
                return False
            else:
                log.info("Mistral检查通过yes")
            
            block_times = await self.config.guild(guild).gpt_block_msg_count()
            block_times += 1
            await self.config.guild(guild).gpt_block_msg_count.set(block_times)
            async with self.config.member_from_ids(guild.id, author.id).stats() as stats:
                stats["msg_last_check_count"] += 1
                if stats["msg_last_check_count"] >= -2:
                    mute_time = 2 ** (stats["msg_last_check_count"] -1)
                    next_mute_time = 2 ** stats["msg_last_check_count"]
                    if stats["msg_last_check_count"] > 14:
                        mute_time = 32768
                        next_mute_time = 32768
                    until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=mute_time)
                    await message.author.edit(timed_out_until=until, reason="[自动]语义分析")
                    if guild.id == 388227343862464513:
                        ntfcn = message.guild.get_channel(1162401982649204777)
                        # await ntfcn.send(f"[{message.author.mention} 的消息经语义分析识别为潜在的不适宜展示消息,已被禁言{mute_time}分钟.\n当前消息内容:```{message_content}```")
                    try:
                        await message.delete()
                    except discord.HTTPException:
                        pass    
                    messagecontent = message_content
                    if len(messagecontent) > 900:
                        messagecontent = messagecontent[:900]
                    await message.channel.send(f"[测试阶段|语义分析] {author.mention} 的消息被归类为广告/诈骗/政治敏感/冒犯/隐私泄露,已被禁言{mute_time}分钟.\n下次触发过滤禁言时间将调整为:{next_mute_time}分\n原始消息已私发给您.管理员可使用&toggleaicheck关闭消息实时分析", delete_after=3600)
                    log.info(f" {author} 的消息被识别为潜在的广告或诈骗消息\n本次禁言时间:{mute_time}分\n下次触发过滤禁言时间将调整为:{next_mute_time}分\n原始消息内容:{messagecontent}")
                    try:
                        await author.send(f"您的消息被识别为潜在的广告或诈骗消息\n本次禁言时间:{mute_time}分\n下次触发过滤禁言时间将调整为:{next_mute_time}分\n您的原始消息内容:```{messagecontent}```\n服务器:{guild.name}\n频道:{channel.name}")
                    except discord.HTTPException:
                        pass
            return True
        
        # await self.config.member_from_ids(guild.id, author.id).msg_last_check_time.set(current_time.isoformat())

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
        isenabled = await self.config.guild(message.guild).pfcheck()
        if not isenabled:
            return False
        guildid = message.guild.id
        userid = message.author.id
        current_time = datetime.datetime.now(datetime.timezone.utc)
        async with self.config.user(message.author).iftrusted() as trusted:
            if trusted:
                return
            
        last_check = await self.config.member_from_ids(guildid, userid).pf_last_check_time()
        if last_check != "":
            last_check_f = datetime.datetime.fromisoformat(last_check)
            if current_time - last_check_f < datetime.timedelta(hours=6):
                # log.info(f"跳过对用户 {userid} 的profile检查,下次检查时间: {last_check_f + datetime.timedelta(hours=6)}")
                return
        
        Authorization = await self.bot.get_shared_api_tokens("dc2auth")
        if Authorization.get("auth") is None:
            return
        
        url = f"https://discord.com/api/v9/users/{userid}/profile?with_mutual_guilds=true&with_mutual_friends_count=false&guild_id={message.guild.id}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,en-US;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Authorization": Authorization.get("auth")
                }
        try:
            response = requests.get(url, headers=headers, timeout=6)
        except requests.exceptions.RequestException as e:
            log.info(f"Bio解析-HTTP请求失败: {e}")
            ntfcnsec = message.guild.get_channel(1162401982649204777) #通知频道-次要-bot命令频道
            await ntfcnsec.send("Bio解析模块异常-HTTP请求超时")
            return

        if response.status_code == 200:
            try:
                json_result = response.json()
                userbio = json_result["user_profile"]["bio"]
                guildbio = json_result["guild_member"]["bio"]
                userpronouns = json_result["user_profile"]["pronouns"]
                guildpronouns = json_result["guild_member_profile"]["pronouns"]
                with open('/home/azureuser/.local/share/Red-DiscordBot/data/sch/cogs/Mod/pf_keywords.json', 'r', encoding='utf-8') as file:
                    data = json.load(file)
                keywords_to_include = data['keywords_to_include']
                if guildpronouns:
                    s_guildpronouns = guildpronouns.lower()
                else:
                    s_guildpronouns = ""
                if userpronouns:
                    s_userpronouns = userpronouns.lower()
                else:
                    s_userpronouns = ""
                if userbio:
                    s_userbio = userbio.lower()
                else:
                    s_userbio = ""
                if guildbio:
                    s_guildbio = guildbio.lower()
                else:
                    s_guildbio = ""

                total_pf = "称谓(guild):" + s_guildpronouns + "\n称谓(user):" + s_userpronouns + "\n介绍(user):" + s_userbio + "\n介绍(guild):" + s_guildbio

                if total_pf:
                    for keyword in keywords_to_include:
                        if keyword in total_pf:
                            until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=72)
                            await message.author.edit(timed_out_until=until, reason="[自动]个人主页潜在广告")

                            if guildid == 388227343862464513:
                                ntfcn = message.guild.get_channel(970972545564168232) #通知频道-仅管理员频道
                                await ntfcn.send(f"{message.author.mention}的个人主页中可能存在广告行为,已被临时禁言,管理员请人工确认.\n当前用户称谓+介绍快照:```{total_pf}```\n如需取消禁言并信任此用户的个人介绍,请输入命令:```&pftrust {message.author.id}```")
                            
                            if guildid == 1056808446030250044:
                                ntfcn = message.guild.get_channel(1097420868902207529) #通知频道-仅管理员频道
                                await ntfcn.send(f"{message.author.mention}的个人主页中可能存在广告行为,已被临时禁言,管理员请人工确认.\n当前用户称谓+介绍快照:```{total_pf}```\n如需取消禁言并信任此用户的个人介绍,请输入命令:```&pftrust {message.author.id}```")

                            try:
                                await message.author.send("经过对用户名/个人简介/消息的评估,您被识别为潜在的广告或垃圾账号,已被禁言并通知管理员人工审核,请耐心等待.若24小时内未处理,请主动联系管理员.如果您是付费菜单的经销商,我们默认您不需要在小助手群组中寻求帮助,为防止间接的广告行为,您可以继续浏览消息,但不再能够发送消息或添加反应.若您的业务范围不包含付费辅助或成人内容,通常经过人工审核后将解除禁言.\n等待过程中请勿退出服务器,否则将被永久封禁")
                            except discord.HTTPException:
                                pass
                            await message.delete()
                            return
                
                await self.config.member_from_ids(guildid, userid).pf_last_check_time.set(current_time.isoformat())
                        
            except:
                log.info("BIO-无法解析JSON结果。")
                ntfcnsec = message.guild.get_channel(1162401982649204777) #通知频道-次要-bot命令频道
                await ntfcnsec.send("Bio解析模块疑似故障-json解析失败")

        else:
            log.info(f"BIO请求失败: {response.status_code}")
            log.info(response.text)
            ntfcnsec = message.guild.get_channel(1162401982649204777) #通知频道-次要-bot命令频道
            await ntfcnsec.send(f"Bio解析模块疑似故障-HTTP ERROR:{response.status_code}")

    async def check_hidelinks(self, message: discord.Message):
        isenabled = await self.config.guild(message.guild).markdowncheck()
        if not isenabled:
            return False
        guildid = message.guild.id

        if message.flags.value == 16384: # 是否是转发消息
            ref_msg = await self.fetch_forwards(message)
            if ref_msg is None:
                return False
            message_content = ref_msg.content
        else:
            message_content = message.content

        pattern_hidelink = re.compile(r'\[([^\]]+)\]\((https?:\/\/[^\s]+) ?\)')
        match_hidelink = pattern_hidelink.search(message_content)
        if match_hidelink:
            relurlpattern = r"(https?://\S+)"
            scanedurls = re.findall(relurlpattern, message_content)

            for surl in scanedurls:
                domainpre = tldextract.extract(surl).domain
                suffix = tldextract.extract(surl).suffix
                domain = domainpre + "." + suffix
                if domain == "discordapp.com":
                    return

            detect_list = ["steamcommunity.com/gift","from steam","Gift 50$"]

            for suslink_p in detect_list:
                if suslink_p in message_content:
                    log.info(f"关键词: {suslink_p}")
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
                        until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=10)
                        await message.author.edit(timed_out_until=until, reason="[自动]softban预处理")
                        await message.channel.send(f"{message.author.mention} 被判定为广告机(steam礼品卡诈骗),已踢出.天上没有馅饼,推广免费礼物、nitro、18+内容的均为诈骗.勿填写勿扫码.")
                        ysch = self.bot.get_user(1044589526116470844)
                        await self.repeattosoftban(message.guild, ysch, message.channel, message.author, "[自动]发送盗号链接(steam礼品卡)")
                        if guildid == 388227343862464513:
                            ntfcn = message.guild.get_channel(970972545564168232) #通知频道-仅管理员频道
                            await ntfcn.send(f"<@{message.author.id}>  ({message.author.name}) 被识别为广告机,已撤回近24h消息并踢出.\n判断原因:steam礼品卡诈骗链接 \n频道:{message.channel.mention}\n当前消息快照:```{message_content}```")

                    except discord.HTTPException:
                        pass
                    log.info(f"限速锁定解除 {len(modmsgs)}")
                    mod_cache[message.author].clear()
                    return True

            try:
                url_pattern = re.compile(r'\((http[s]?://[^)]*)')
                urls = url_pattern.findall(message_content)
                if len(urls) > 1:
                    await message.delete()
                    await message.channel.send(f'{message.author.mention} 复合markdown', delete_after=180)

                response = requests.head(urls[0], allow_redirects=True, timeout=3)
                content_type = response.headers.get('content-type')
                if content_type:
                    if "image" in content_type:
                        log.info(f"链接为图片,跳过: {urls}")
                        return
            except:
                log.info("md-hidelink深度检测失败")
                pass
            
            await message.delete()
            await message.channel.send(f'{message.author.mention} 请勿使用markdown语法隐藏真实网址,原始消息已私发给您,请重新编辑', delete_after=60)
            try:
                await message.author.send(f"请勿使用markdown语法隐藏真实网址,请重新编辑.您的原始消息内容: ```{message_content}```")
            except discord.HTTPException:
                pass
            if guildid == 388227343862464513:
                ntfcn = message.guild.get_channel(1162401982649204777) #通知频道-次要-bot命令频道
                await ntfcn.send(f"{message.author.mention} ({message.author.name}) 的消息中存在使用Markdown语法隐藏的网址. \n频道:{message.channel.mention}\n当前消息快照:```{message_content}```")
            return True
        return False

    async def decodeqr(self, message: discord.Message):
        isenabled = await self.config.guild(message.guild).qrcodecheck()
        if not isenabled:
            return False
        
        guildid = message.guild.id
        if guildid != 388227343862464513:
            return


        if message.flags.value == 16384: # 是否是转发消息
            ref_msg = await self.fetch_forwards(message)
            if ref_msg is None:
                return False
            s_message = ref_msg
        else:
            s_message = message
            
        if s_message.attachments:
            ntfcn = message.guild.get_channel(1162401982649204777) #通知频道-次要-bot命令频道
            count_mk = 0
            for attachment in s_message.attachments:
                if attachment.filename.endswith('.png') or attachment.filename.endswith('.jpg') or attachment.filename.endswith('.jpeg'):
                    await attachment.save(f"/home/azureuser/bot_tmp/atc/temp_image{message.id}_{count_mk}.png")
                    img = Image.open(f"/home/azureuser/bot_tmp/atc/temp_image{message.id}_{count_mk}.png")
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
                    os.remove(f"/home/azureuser/bot_tmp/atc/temp_image{message.id}_{count_mk}.png")        
                count_mk += 1

    async def checkurl(self, message: discord.Message):
        isenabled = await self.config.guild(message.guild).urlblacklistcheck()
        if not isenabled:
            return False
        guildid = message.guild.id

        if message.flags.value == 16384: # 是否是转发消息
            ref_msg = await self.fetch_forwards(message)
            if ref_msg is None:
                return False
            message_content = ref_msg.content
        else:
            message_content = message.content

        if "weixin110.qq.com" in message_content or "weixin.qq.com/g" in message_content or "u.wechat.com" in message_content or "jq.qq.com" in message_content or "qm.qq.com" in message_content or "group_code" in message_content or "qr.alipay.com" in message_content or "wxp://" in message_content or "discord.com/ra/" in message_content or "gg.gg/" in message_content or "u.to/" in message_content or "t.ly/" in message_content:
            await message.delete()
            await message.channel.send(f"{message.author.mention} 您的消息中存在可疑链接,已被撤回.")
            if guildid == 388227343862464513:
                ntfcn = message.guild.get_channel(1162401982649204777) #通知频道-次要-bot命令频道
                await ntfcn.send(f"{message.author.mention}的消息中存在可疑链接(收付款/个人或群名片/微信辅助验证/discord登录). \n 当前消息快照:```{message.content}```")
            try:
                await message.author.send(f"您发送的消息 `{message_content}` 被识别为包含可疑链接,已被撤回.")
            except discord.HTTPException:
                log.info(f"无法私发消息给用户 {message.author.id}")
            return True
        return False
    
    async def VT_file_scan(self, file_path, message: discord.Message):
        VT_key = await self.bot.get_shared_api_tokens("virustotal")
        if VT_key.get("apikey") is None:
            return
        url = 'https://www.virustotal.com/api/v3/files'
        headers = {'x-apikey': VT_key.get("apikey")}
        with open(file_path, 'rb') as file_f:
            response = requests.post(url, files={'file': file_f}, headers=headers, timeout=6)
        os.remove(file_path)
        if response.status_code == 200:
            json_response = response.json()

            data = json_response['data']
            aid = data['id']

            url = f'https://www.virustotal.com/api/v3/analyses/{aid}'
            headers = {'x-apikey': VT_key.get("apikey")}

            self.mthread2 = threading.Thread(target=self.call_async_VT_file_scan, args=(url, message))
            self.mthread2.start()
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
                response2 = requests.get(url, headers=headers, timeout=6)
                
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
            if harmc > 1 or susc > 2:
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
                httprlt = requests.post(restapi_sendmsg, json=data, headers=headers, timeout=6)
            return
            

    async def VT_url_scan(self, susurl, message: discord.Message):

        VT_key = await self.bot.get_shared_api_tokens("virustotal")
        if VT_key.get("apikey") is None:
            return
        url = 'https://www.virustotal.com/api/v3/urls'
        query_params = {'url': susurl}
        headers = {'x-apikey': VT_key.get("apikey")}

        response = requests.post(url, params=query_params, headers=headers, timeout=6)
        if response.status_code == 200:
            json_response = response.json()

            data = json_response['data']
            aid = data['id']

            url = f'https://www.virustotal.com/api/v3/analyses/{aid}'
            headers = {'x-apikey': VT_key.get("apikey")}
            i = 5
            while i > 0:

                i = i - 1
                response2 = requests.get(url, headers=headers, timeout=6)

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
            if harmc > 1 or susc > 2:            
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
                requests.post(restapi_sendmsg, json=data, headers=headers, timeout=6)
        return


    async def filesafecheck(self, message: discord.Message):
        isenabled = await self.config.guild(message.guild).filevtcheck()
        if not isenabled:
            return False

        if message.flags.value == 16384: # 是否是转发消息
            ref_msg = await self.fetch_forwards(message)
            if ref_msg is None:
                return False
            message_final = ref_msg
        else:
            message_final = message

        if len(message_final.attachments) > 0:
            for attachment in message_final.attachments:
                file_path = f'/home/azureuser/bot_tmp/atc/{attachment.filename}'
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
        isenabled = await self.config.guild(message.guild).urlvtcheck()
        if not isenabled:
            return False

        if message.flags.value == 16384: # 是否是转发消息
            ref_msg = await self.fetch_forwards(message)
            if ref_msg is None:
                return False
            message_content = ref_msg.content
        else:
            message_content = message.content

        if message.channel.id == 1254956902308122664: #bypass 进群验证
            return
        
        content = message_content
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
            self.mthread1 = threading.Thread(target=self.call_async_VT_url_scan, args=(url, message))
            self.mthread1.start()

    async def check_ping_everyone_here(self, message: discord.Message):
        isenabled = await self.config.guild(message.guild).badmentioncheck()
        if not isenabled:
            return False

        if "@everyone" in message.content or "@here" in message.content:

            if message.guild.id == 388227343862464513:
                if "discord.com" in message.content or "discord.gg" in message.content:
                    until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=30)
                    await message.author.edit(timed_out_until=until, reason="[自动]mass mention+潜在的邀请链接")
                    try:
                        await message.delete()
                        await message.channel.send(f'{message.author.mention} 您的消息可能包含邀请链接,且存在批量提及行为,被判断为广告[可信度较高],已禁言30min并通知管理员,请等待人工复核', delete_after=600)
                    except:
                        pass
                    ntfcn = message.guild.get_channel(970972545564168232) #通知频道-次要-bot命令频道
                    await ntfcn.send(f"{message.author.mention}试图mention everyone or here.消息中可能存在邀请链接,已禁言30min \n 当前消息快照:```{message.content}```")
                else:
                    try:
                        await message.delete()
                        await message.channel.send(f'{message.author.mention} 您不具有ping everyone or here权限.', delete_after=60)
                    except:
                        pass
                    ntfcn = message.guild.get_channel(1162401982649204777) #通知频道-次要-bot命令频道
                    await ntfcn.send(f"{message.author.mention}试图mention everyone or here. \n 当前消息快照:```{message.content}```")
                    try:
                        await message.author.send(f"您的原始消息是: ```{message.content}```")
                    except discord.HTTPException:
                        pass
            return True

    async def shadowfunc(self, message: discord.Message):
        isenabled = await self.config.guild(message.guild).shadowmutecheck()
        if not isenabled:
            return False

        # check shadow mute
        ifshadowmute = await self.config.user(message.author).shadow_mute()
        if ifshadowmute:
            await message.delete()
            return True
        
        return False

    @commands.Cog.listener()
    async def on_automod_action(self, execution):
        isenabled = await self.config.guild(execution.guild).automodcheck()
        if not isenabled:
            return False
        detected = await self.check_duplicates_automod(execution)
        if not detected:
            await self.ckeck_automod_content(execution)
 
    @commands.Cog.listener()
    async def on_message_edit(self, _prior, message):
        isenabled = await self.config.guild(message.guild).editcheck()
        if not isenabled:
            return False

        if _prior.content == message.content:
            return
        author = message.author
        if message.guild is None or self.bot.user == author:
            return

        if await self.bot.cog_disabled_in_guild(self, message.guild):
            return
        
        if message.flags.value == 16384: # 是否是转发消息
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

        await self.check_mention_spam(message)
        await self.muteadacc(message)
        deleted = await self.check_hidelinks(message)
        if not deleted:
            deleted = await self.check_ping_everyone_here(message)
            if not deleted:
                deleted = await self.checkurl(message)
                if not deleted:
                    await self.affcodecheck(message)
                    await self.urlsafecheck(message)
                    await self.filesafecheck(message)
                    await self.openaicheck(message)

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
                    await self.decodeqr(message)
                    deleted = await self.checkurl(message)
                    if not deleted:
                        deleted = await self.shadowfunc(message)
                        if not deleted:
                            await self.affcodecheck(message)
                            await self.urlsafecheck(message)
                            await self.filesafecheck(message)
                            await self.autorole(message)
                            await self.openaicheck(message)

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

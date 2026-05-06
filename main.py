import os
import json
import uuid
import tempfile
import aiohttp
from PIL import Image as PILImage, ImageSequence

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Image, Plain

@register("meme_reader_pro", "YourName", "支持GIF逐帧拆解的梗图解读插件", "2.0.0")
class MemeReaderPro(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # 配置文件路径，现在只负责保存用户设定的帧数
        self.config_path = os.path.join(os.path.dirname(__file__), "meme_config.json")
        self.config = {
            "max_frames": 4  # GIF 默认最大提取帧数
        }
        self.load_config()

    def load_config(self):
        """加载本地配置"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self.config.update(json.load(f))
            except Exception as e:
                logger.error(f"加载配置文件失败: {e}")

    def save_config(self):
        """保存配置到本地"""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")

    # ================= 指令1：动图提取参数设置 =================
    @filter.command("解读设置")
    async def settings(self, event: AstrMessageEvent, action: str = "", value: str = ""):
        """
        指令：/解读设置 设置帧数 [数字]
        """
        if action == "设置帧数":
            if not value.isdigit() or int(value) < 1 or int(value) > 10:
                yield event.plain_result("请提供 1 到 10 之间的数字！过多的帧数会导致大模型报错。")
                return
            self.config["max_frames"] = int(value)
            self.save_config()
            yield event.plain_result(f"✅ GIF 动图最大解析帧数已设置为：{value} 帧")
        else:
            yield event.plain_result(
                "⚙️ 【解读插件设置指南】\n"
                "1. /解读设置 设置帧数 [数字] (设置GIF提取最大帧数)\n\n"
                "💡 提示：如果需要切换解读使用的 AI 模型，请直接使用 AstrBot 原生功能（如在后台切换默认模型）。"
            )

    # ================= 指令2：表情包/动图解读 =================
    @filter.command("解读")
    async def read_meme(self, event: AstrMessageEvent):
        """发送 /解读 并附带图片/动图"""
        img_url_or_path = None
        for component in event.get_messages():
            if isinstance(component, Image):
                img_url_or_path = component.url or component.file 
                break

        if not img_url_or_path:
            yield event.plain_result("请在发送指令时，同时附带一张表情包图片或 GIF 动图！")
            return

        yield event.plain_result("🤔 正在端详这张图...")

        temp_files_to_clean = []
        try:
            # 【符合官方文档规范】直接获取系统当前正在使用的提供商
            provider = self.context.get_using_provider()
            if provider is None:
                yield event.plain_result("❌ 错误：AstrBot 当前未配置可用的大模型提供商。")
                return

            # 判断并处理 GIF 动图
            image_urls = []
            is_gif = img_url_or_path.lower().endswith('.gif') or "gif" in img_url_or_path.lower()
            
            if is_gif:
                yield event.plain_result(f"🎞️ 检测到动图，正在均匀提取 {self.config['max_frames']} 帧关键画面...")
                frames, temp_files_to_clean = await self.process_gif(img_url_or_path, self.config["max_frames"])
                image_urls = frames
            else:
                image_urls = [img_url_or_path]

            # 构建提示词
            prompt = "你是一个精通互联网黑话和梗图的冲浪高手。"
            if is_gif:
                prompt += f"用户提供了一个 GIF 动图的 {len(image_urls)} 帧连续截图。请根据这几张图的时间顺序：\n"
            else:
                prompt += "请观察用户提供的这张表情包：\n"
                
            prompt += (
                "1. 提取出画面上的关键文字内容（如果有）。\n"
                "2. 结合画面内容和动作，用幽默、简短的语言解释这个梗图想表达的情绪、潜在的梗或是适用的聊天场景。"
            )

            # 调用视觉大模型
            response = await provider.text_chat(
                prompt=prompt,
                session_id=event.session_id, 
                image_urls=image_urls         
            )

            result_text = response.completion_text
            logger.info(f"成功解析，模型返回: {result_text}")
            yield event.plain_result(f"🔍 【梗图解读报告】\n\n{result_text}")

        except Exception as e:
            logger.error(f"表情包解析异常: {e}")
            yield event.plain_result(f"解析失败！请确认当前 AstrBot 后台默认的模型支持视觉(看图)能力。详细报错：{str(e)}")

        finally:
            # 清理本地缓存的 GIF 拆解帧文件
            for file_path in temp_files_to_clean:
                if os.path.exists(file_path):
                    os.remove(file_path)

    # ================= 核心逻辑：GIF 提取帧 =================
    async def process_gif(self, url_or_path: str, max_frames: int):
        """
        下载(如需要)并均匀拆解 GIF
        返回: (抽取出的帧的本地路径列表, 需要清理的临时文件列表)
        """
        temp_files = []
        local_gif_path = url_or_path
        
        # 如果是网络URL，先下载到本地临时文件
        if url_or_path.startswith("http"):
            temp_gif = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4().hex}.gif")
            async with aiohttp.ClientSession() as session:
                async with session.get(url_or_path) as resp:
                    if resp.status == 200:
                        with open(temp_gif, "wb") as f:
                            f.write(await resp.read())
                        local_gif_path = temp_gif
                        temp_files.append(temp_gif)

        # 打开 GIF 并逐帧提取
        extracted_paths = []
        with PILImage.open(local_gif_path) as img:
            frames = [frame.copy() for frame in ImageSequence.Iterator(img)]
            total_frames = len(frames)
            
            step = max(1, total_frames // max_frames)
            
            for i in range(0, total_frames, step):
                if len(extracted_paths) >= max_frames:
                    break
                frame_img = frames[i].convert("RGB") # 转为RGB，去掉透明通道防报错
                frame_path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4().hex}.jpg")
                frame_img.save(frame_path, "JPEG")
                extracted_paths.append(frame_path)
                temp_files.append(frame_path)
                
        return extracted_paths, temp_files


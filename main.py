from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Image # 必须引入 Image 组件才能识别图片

@register("meme_reader", "YourName", "提取并解读聊天中的表情包梗图", "1.0.0")
class MemeReader(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        logger.info("表情包解读插件已成功初始化！")

    # 注册指令。发送 `/解读 [图片]` 就会触发这个指令
    @filter.command("解读")
    async def read_meme(self, event: AstrMessageEvent):
        """发送 /解读 并附带一张图片，插件会调用多模态大模型解释这个表情包""" 
        
        img_url = None
        message_chain = event.get_messages() # 用户所发的消息的消息链
        
        # 1. 遍历消息链寻找图片组件
        for component in message_chain:
            if isinstance(component, Image):
                # 获取图片的网络链接或本地路径
                img_url = component.url or component.file 
                break

        # 如果用户没发图片
        if not img_url:
            yield event.plain_result("请在发送『/解读』指令时，同时附带一张表情包图片哦！")
            return

        yield event.plain_result("🤔 正在端详这张表情包...")

        try:
            # 2. 构建提示词
            system_prompt = (
                "你是一个精通互联网黑话和梗图的网络冲浪高手。请观察用户提供的这张表情包：\n"
                "1. 提取出图片上的所有文字内容（如果有的话）。\n"
                "2. 结合画面内容，用幽默、简短的语言解释这个表情包想表达的情绪、潜在的梗或是适用的聊天场景。"
            )

            # 3. 获取 AstrBot 默认配置的大模型提供商
            provider = self.context.get_using_provider()
            
            if provider is None:
                yield event.plain_result("错误：没有配置可用的大模型提供商。")
                return

            # 4. 调用大模型（请确保后台配置的是支持视觉 Vision 的模型）
            response = await provider.text_chat(
                prompt=system_prompt,
                session_id=event.session_id, 
                image_urls=[img_url]         
            )

            result_text = response.completion_text
            logger.info(f"成功解析表情包，模型返回: {result_text}")
            yield event.plain_result(f"🔍 【表情包解读报告】\n\n{result_text}")

        except Exception as e:
            logger.error(f"表情包解析异常: {e}")
            yield event.plain_result(f"解析失败了！请检查后台配置的模型是否支持视觉(看图)能力。错误信息：{str(e)}")

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        logger.info("表情包解读插件已被卸载或停用。")

# 大肥鱼桌宠（自研版）

一个干净的 Python 桌面桌宠，复用开源项目的动画素材。

**总有一天所有人都要控大肥鱼**

## 功能

- 透明无边框窗口，显示 Q 版角色动画（默认不置顶，可在右键菜单开启「置顶」）
- 动画链状态机：随机动作 
- 点击回应、拖拽
- 自动移动
- 聊天气泡
- 点击桌宠弹出圆角聊天输入框
- 把文件拖到桌宠身上可以「吃掉」
- 右键菜单
- 设置对话框：配置 LLM 接口
- 系统托盘图标

## 依赖

需要 Python 3.9+，安装：

```bash
pip install -r requirements.txt
# 即：PySide6、imageio-ffmpeg、Pillow
```

## 运行

```bash
python main.py
```

动画素材已随项目附带（`assets/videos/`），clone 下来直接就能跑。
如果素材在别处，用 `--assets` 指定：

```bash
python main.py --assets "D:\你的路径\videos"
```

## 配置 API

右键桌宠 →「设置…」，填写以下内容后点「保存」，立即生效并写入 `config.json`：

| 字段 | 说明 | 示例 |
| --- | --- | --- |
| 接口地址 | OpenAI 兼容的 Base URL | `your-base-url` |
| API Key | 接口密钥，默认打码，点右侧「显示」可查看 | `sk-...` |
| 模型 | 模型名 | `your-model-id` |
| 系统提示词 | 桌宠人设，留空则用默认 | 你是"大肥鱼"…… |

对话框里的「测试连接」会发一条最小请求验证配置是否正确；
「恢复默认」填入内置默认值（按下「保存」才生效）。

配置保存在 `config.json`，首次运行会自动生成。想手动改可以参考
`config.example.json`。


## 文件结构

```
my-pet/
├── main.py             # 入口 + 托盘
├── pet_window.py       # 主窗口（透明窗口、动画链、拖拽、移动、菜单、拖放喂食）
├── webm_player.py      # webm 透明动画播放器（imageio-ffmpeg 解码）
├── speech_bubble.py    # 聊天气泡
├── catalog.py          # 扫描资源目录构建动画清单
├── config.py           # 配置读写（config.json）
├── settings_dialog.py  # 设置对话框（API 配置 + 测试连接）
├── chat_input.py       # 圆角卡片聊天输入框
├── eat_confirm.py      # 「吃掉」确认框（圆角卡片）
├── file_actions.py     # 文件类型校验 + 移入回收站
├── llm_client.py       # LLM 聊天客户端（读 config.json）
├── requirements.txt
├── config.example.json # 配置示例
├── assets/videos/      # 动画素材（91 个 webm）
├── LICENSE             # MIT（仅代码）
└── ASSET_LICENSE.md    # 素材许可（CC BY-NC-SA 4.0）
```

## 许可

- **程序代码**：MIT License，见 `LICENSE`
- **动画素材**（`assets/videos/` 下 91 个 webm）：来自
  [CodexDafeiyuPet](https://github.com/PC2005-cloud/dsh-pet)，
  采用 CC BY-NC-SA 4.0，**仅限非商业使用**，详见 `ASSET_LICENSE.md`

本项目是非官方同人项目，与 DeepSeek、OpenAI 及素材作者不存在隶属、赞助或背书关系。

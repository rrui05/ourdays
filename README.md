# Our Days

把本机微信聊天记录变成一片会呼吸的晚霞：甜蜜词条、双方统计、自定义关键词对比，以及会引用真实原消息的 AI 问答。

## 本地运行

```powershell
conda activate ourdays
Set-Location D:\zzr\ourdays
python .\export_wechat_day.py
uvicorn app:app --reload
```

打开 <http://127.0.0.1:8000>。AI 使用根目录 `.env` 中的 `APIKEY`，模型固定为 `gemini-3.7-flash`。

导出其他好友或日期范围：

```powershell
python .\export_wechat_day.py --wechat-id li82218030 --start 2026-07-22 --end 2026-09-04
```

默认写入 `data/chat.json`；每条 `message` 只含 `time`、`sender_name`、`type`、`content` 四个字段。

## 部署到 Render

先生成适合 Render Secret File 的压缩文本：

```powershell
python .\export_wechat_day.py --render-secret
```

这会额外生成 `data/chat.json.xz.b64`。当前文件约 391 KiB，低于 Render Secret File 合计 1 MB 的限制；它和原始 JSON 都已被 `.gitignore` 排除。

1. 新建 GitHub 仓库并推送项目，建议使用私有仓库。不要强制提交 `.env`、`data/`、`exports/` 或 `wechat_extract_cache/`。
2. 在 Render Dashboard 选择 **New > Blueprint**，连接仓库。根目录的 `render.yaml` 会创建新加坡区的免费 Python Web Service。
3. 创建时填写 Render 提示的 `APIKEY` 和 `SITE_PASSWORD`。访问密码建议使用足够长的 ASCII 字符串。
4. 服务出现后打开 **Environment > Secret Files > Add Secret File**：Filename 填 `chat.json.xz.b64`，Contents 粘贴本地同名文件的全部内容，然后保存。

Windows 下可直接复制压缩文本：

```powershell
Get-Content -Raw .\data\chat.json.xz.b64 | Set-Clipboard
```

保存 Secret File 会触发一次新部署。部署完成后打开 Render 给出的 `onrender.com` 地址，输入 `SITE_PASSWORD` 即可。以后更新聊天记录时，重新运行带 `--render-secret` 的导出命令并替换 Secret File 内容。

`render.yaml` 已固定 Python 3.12.14、绑定 `0.0.0.0:$PORT` 并配置健康检查。`region: singapore` 创建后不能更改，如需别的区域请在第一次部署前修改。

Render 免费 Web Service 连续 15 分钟没有入站请求会休眠，下次打开通常需要约一分钟唤醒。免费实例没有持久磁盘，所以线上只读取 Secret File 快照，不运行 Windows 微信导出，也不在运行时保存数据。详见 [Render Free 文档](https://render.com/docs/free) 和 [Secret Files 文档](https://render.com/docs/configure-environment-variables)。

## 检查

```powershell
python -m unittest
node --check .\static\app.js
```

`.env`、聊天数据和解密缓存不会进入 Git；`WECHATAUTO_LICENSE` 是本地微信读取实现的原许可证，请保留。

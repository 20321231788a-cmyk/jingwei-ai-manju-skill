# 视觉画风库与自定义画风锁（Style Presets & Lock）

本技能**不再将任何单一画风写死为所有新作品的唯一默认值**。作品画风由用户在新建项目时选定内置主流画风或自定义提供，并在[项目专属技能](project-skills.md)与各集 `制作数据.json` 中跨集锁定。

---

## 一、新建项目强制画风问询机制（未指定必提问）

启动新作品时，Agent 先检索用户输入与原件设定中是否已明确画风：
1. **用户已指定画风（或给出了参考图）：** 直接匹配对应内置预设，或提炼用户的自定义画风写入项目专属技能与 `制作数据.json`（`style_name` + `style`），不重复打扰用户。
2. **用户未指定画风：** **Agent 必须在创建资产（角色图/场景图）和编写分镜提示词之前，先向用户提问确认画风**（可调用 `ask_question` 或清晰列出下表选项 + 自定义入口）：
   - 给出内置 6 种主流画风的简洁说明与适用题材；
   - 明确提示：**“也可直接描述你想要的任意画风，或发我 1–3 张风格参考图由我提取锁定。”**
   - 未获用户确认前，不得擅自默认用旧项目的 `r2混合媒介` 直接批量出图。

---

## 二、内置六大主流画风预设库

| 预设代号 | `style_name`（看板标签） | 视觉特征与适用题材 | 提示词头部精炼注入模板（≤25字，适配Wan3/SD2.0头部减脂） |
| --- | --- | --- | --- |
| **S1** | `r2混合媒介` | **3D半写实CG角色 + 现实摄影背景**：柔缎瓷感肤质、精致国漫/BJD美型骨相、发丝分明；搭配真实摄影级建筑材料与有源光影，共用透视与接触阴影。<br>**适用**：都市异能、现代民俗、末世悬疑、现代爽剧。 | `半写实3D CG人物融入真实摄影实景，共用透视与有源光影` |
| **S2** | `2D厚涂韩漫` | **高清商业条漫 / 番剧厚涂赛璐璐风**：锐利干净的线条、强对比硬朗明暗块面、高饱和发丝与瞳孔高光、戏剧化氛围光晕。<br>**适用**：都市逆袭、校园打脸、重生复仇、现代言情。 | `高清厚涂韩漫二次元画风，干净线稿与强对比赛璐璐光影` |
| **S3** | `3D国漫玄幻` | **全场景统一次世代3D国漫CG**：角色与宏大仙侠建筑统一3D渲染、高精盔甲织物物理褶皱、体积光束与高密度粒子特效。<br>**适用**：修仙、高武、宗门争霸、仙侠大场面打斗。 | `次世代3D国漫玄幻CG质感，统一3D场景与强体积光效` |
| **S4** | `新中式水墨` | **东方工笔水墨与现代CG融合**：宣纸淡雅肌理底韵、工笔勾勒骨相轮廓、青绿/朱砂局部高饱和点染、写意墨气与留白意境。<br>**适用**：古风权谋、硬核武侠、中式志怪悬疑。 | `新中式工笔水墨国风，宣纸肌理、墨韵留白与朱砂点染` |
| **S5** | `电影写实真人` | **写实电影胶片质感**：真实皮肤纹理与汗渍伤痕、实拍光学浅景深、高反差硬光塑形与轻微胶片质感（不做网红磨皮）。<br>**适用**：刑侦悬疑、商战博弈、写实末日、强冲突真人感短剧。 | `电影级写实摄影画风，真实肤质伤痕、光学景深与硬光塑形` |
| **S6** | `暗黑赛博霓虹` | **高对比暗夜霓虹科幻风**：冷青/洋红双色轮廓逆光、雨夜湿石与玻璃镜面强反射、硬朗金属机甲与全息投影材质。<br>**适用**：赛博朋克、未来科幻、都市异能夜战。 | `暗黑赛博朋克霓虹画风，冷暖强逆光轮廓与镜面高反光` |

### 各画风生图美学注入配方

直接供生成**角色四视角设定图**与**无人物场景底图**时选用（人物融合[三点雕塑布光与高定审美](delivery.md#人物四视角设定图character_sheet)，场景融合[电影静帧构图与60-30-10色彩脚本](delivery.md#无人物场景图与道具图background--prop)）：

各画风的人物设定图和表情图提示词均须写明所选浅色底色，例如“干净的浅暖灰背景，同组各视角底色一致”，再接下表人物光效配方。

| 预设代号 | 人物生图渲染与光效配方 | 场景生图摄影与美术配方 |
| --- | --- | --- |
| **S1 (`r2混合媒介`)** | `refined semi-realistic 3D cinema CG cast, sculpted cheekbones, luminous translucent porcelain SSS skin, crisp hair & shoulder rim light, glossy dual eye catchlights, couture fabric contrast` | `cinema film still, 35mm anamorphic or f/2.8 prime lens, soft foreground framing bokeh, atmospheric depth haze, 60-30-10 warm-cool color script, aged prop patina, dappled sunlight or practical glow` |
| **S2 (`2D厚涂韩漫`)** | `high-end commercial webtoon semi-painterly illustration, razor-clean linework, bold cel-sculpted shadows, luminous jewel irises, flowing multi-strand hair, dramatic color-tinted rim light` | `theatrical anime background art, crisp painterly brushstrokes, broad clean color planes, expressive atmospheric bloom, clear foreground-to-far depth separation` |
| **S3 (`3D国漫玄幻`)** | `next-gen 3D donghua blockbuster CG, intricate metallic embroidery & multilayer silk drapes, jade-translucent SSS skin, crisp hair-crown rim light, cinematic studio key-to-fill ratio` | `Unreal Engine 5 epic xianxia environment art, volumetric god rays, mist-layered distant peaks, carved stone & weathered timber textures, cool cyan-teal shadows vs gilded highlights` |
| **S4 (`新中式水墨`)** | `modern Chinese gongbi ink-wash fused with CG sculpting, calligraphic bone-line contour, subtle xuan-paper texture, restrained celadon & ink palette with cinnabar-gold focal accents` | `poetic neo-Chinese ink-wash film still, negative-space composition, wet-ink mountain mist depth, weathered architectural shadows, hand-brushed calligraphy signage` |
| **S5 (`电影写实真人`)** | `theatrical 35mm cinema portrait still, authentic skin micro-luster without plastic smoothing, sculpted 3:1 key-to-fill lighting, crisp rim separation, fine textile weave, subtle film grain` | `ARRI cinema film frame, motivated practical lights against cool ambient fill, smooth highlight roll-off, foreground architectural framing, moody atmospheric haze` |
| **S6 (`暗黑赛博霓虹`)** | `high-contrast dark sci-fi concept CG, matte techwear vs brushed metal & translucent trim contrast, bi-color cyan-magenta rim lighting tearing character silhouette cleanly from backdrop` | `cinematic cyberpunk night rain still, deep clean shadows with selective neon focal glow, wet asphalt & glass crisp reflections, controlled cyan atmospheric rain mist` |

---

## 三、用户自定义画风（`custom`）接入规范

当用户选择“自定义画风”时（文字描述或提供参考图）：
1. **文字描述：** 将用户提供的核心媒介（如 `美式复古美漫`、`像素复古RPG`、`皮克斯3D卡通`、`诡异民俗剪纸风`）、色彩倾向、光影对比和材质特征提炼为两项：
   - `style_name`：不超过 10 字的简短画风标签（显示在看板顶部与导出标签）。
   - `style`：60–120 字的完整画风定义，用于生图与项目专属技能存档。
2. **参考图提取：** 若用户直接上传 1–3 张目标画风参考图，Agent 必须先用文字提取该图的**渲染媒介、线条/体块特征、色彩饱和度、光比与阴影处理**，写入 `style_name` 和 `style`，再经用户确认后锁定；注意**只提取画风，不提取参考图中的无关角色脸型和剧情**。

---

## 四、画风锁与多模型提示词减脂兼容

1. **一剧一锁，跨集统一：** 画风一旦在新建项目时由用户确认，同时写入 `<作品名>/.agents/skills/<项目技能名>/SKILL.md` 的「视觉画风锁」与每集 `制作数据.json` 的 `style_name` / `style` 字段。
2. **不挤占动作权重：** 在编译 Wan3.0（头部 ≤110字）和 SD2.0（头部 ≤95字）的 `prompt_text` 时，**只取上表或自定义画风提炼后的 1 句核心质感短语（≤25字）放进头部**，禁止把 120 字的画风说明书全文抄进每段视频提示词开头。
3. **H3 分支隔离：** 使用 H3 时，将选定画风的质感细节写入 `subject_definitions` / `summary` / `retention_analysis`，`detailed_description` 里的 `[Shot N]` 仍保持零静态材质词、全用强爆发英文动词。
4. **资产图一致与生图美学直注：** 生成角色四视角图与无人物场景底图时，严格沿用本剧锁定的画风预设并直接套用上表对应画风的「生图美学注入配方」（结合[素材审美与电影布光规范](delivery.md#素材)，由模型直接判断执行，不增加额外审批流程），同时视频提示词头部仍只取上表 ≤25 字核心短语保持减脂；同一部剧不混用冲突媒介（如一镜2D韩漫、下一镜3D写实）。

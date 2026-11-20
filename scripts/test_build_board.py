"""Offline exporter regression tests; all artifacts live in temporary directories."""
from copy import deepcopy
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import build_board as board


def fixture(base):
    (base / '原件.txt').write_text('测试原件：甲问路，乙指向门口。甲踏前，乙挡住其手臂，甲收手。', encoding='utf-8')
    shutil.copyfile(board.ASSETS / 'character-reference-layout-r2.png', base / '人物图.png')
    data = dict(project='导出器测试（非正式剧集）', episode='TEST', title='长短镜头验证', source='原件.txt',
                aspect_ratio='16:9', style='r2混合媒介', director_style='同框观察人物距离，复杂接触改用短镜头。',
                review_status='reviewed', pending_items=[], references=[dict(id='C01', type='character_sheet',
                path='人物图.png', purpose='仅用于测试本地图片显示与整图绑定', verified=True)], units=[])
    for uid, duration, kind in [('U01', 12, 'long'), ('U02', 4, 'short')]:
        detail = 'Semi-realistic 3D character CG in a realistic environment with shared perspective and lighting.\n[Shot 1] The camera observes both characters. <Subject 1> (S1) asks, <d>[Chinese] 门在哪里？</d>'
        chinese = '半写实3D角色CG，现实材质背景，共用透视与光影。\n[Shot 1] 双人中景观察。<Subject 1> (S1) 问道：<d>[Chinese] 门在哪里？</d>'
        if uid == 'U01':
            detail += '\n[Shot 2] At 00:02.750, the camera cuts to the listener pointing toward the door.'
            chinese += '\n[Shot 2] At 00:02.750, 切到听者近景，他抬手指向门口。'
        data['units'].append(dict(id=uid, title='测试单元', source_locator='测试原件全文', duration_s=duration,
            kind=kind, scene='室内门旁', framing='双人中景', action='甲与乙交流，按原件动作承接。',
            camera='按实际动作和回应观察，真实切点见H3正文。', prompt_zh={'detailed_description':chinese}, dialogue=['甲：门在哪里？'],
            sound='人声与室内底声', continuity='动作方向与手部接触状态连续。', references=['C01'],
            prompt=dict(subject_definitions='<Subject 1> uses the identity in <Picture 1>.',
                        summary='[reference generation] A continuity test.',
                        retention_analysis='<Subject 1>: fully_preserved - identity only.',
                        detailed_description=detail, overall_soundscape='Quiet room tone.', non_diegetic_music='None.')))
    return data


class BoardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.data = fixture(self.base)

    def tearDown(self):
        self.temp.cleanup()

    def test_real_shots_without_fixed_time_grid(self):
        self.assertEqual(board.validate(self.data, self.base, True), ([], []))
        data = deepcopy(self.data)
        data['units'][0]['prompt_zh']['detailed_description'] = data['units'][0]['prompt_zh']['detailed_description'].replace('00:02.750', '00:03.000')
        self.assertTrue(board.validate(data, self.base, True)[0])

    def test_official_cut_order_and_duration(self):
        self.assertFalse(board.validate_shots('[Shot 1] Open. [Shot 2] At 00:02.750, Cut.', 12, 'U01'))
        for detail in ('[Shot 1] At 00:00.000, Open.',
                       '[Shot 1] Open. [Shot 2] No cut time.',
                       '[Shot 1] Open. [Shot 2] At 00:12.000, Cut.',
                       '[Shot 1] Open. [Shot 3] At 00:02.000, Cut.',
                       '[Shot 1] Open. [Shot 2] At 00:03.000, Cut. [Shot 3] At 00:02.000, Cut.'):
            with self.subTest(detail=detail):
                self.assertTrue(board.validate_shots(detail, 12, 'U01'))

    def test_generation_adoption_interval_is_bounded_and_matches_narrative(self):
        unit=self.data['units'][0]
        unit['duration_s']=15
        unit['generation']=dict(protocol='rb-v1',preset='easy_15',width=1344,height=768,
                                narrative_seconds=9,adopted_interval=[0,9])
        self.assertEqual(board.validate(self.data,self.base,True),([],[]))
        unit['generation']['adopted_interval']=[0,16]
        self.assertTrue(board.validate(self.data,self.base,True)[0])
        unit['generation']['adopted_interval']=[0,8]
        self.assertTrue(board.validate(self.data,self.base,True)[0])

    def test_chinese_display_does_not_replace_submission_prompt(self):
        original = deepcopy(self.data['units'][0]['prompt'])
        result = board.render(self.data, self.base, self.base/'看板.html', [])
        self.assertIn('H3镜头（中文）', result)
        self.assertIn('[Shot 2] At 00:02.750', result)
        self.assertIn('切到听者近景', result)
        self.assertEqual(self.data['units'][0]['prompt'], original)
        self.data['units'][0]['prompt_zh']['detailed_description'] = self.data['units'][0]['prompt_zh']['detailed_description'].replace('门在哪里？', '你是谁？')
        self.assertTrue(board.validate(self.data, self.base, True)[0])

    def test_missing_translation_is_an_honest_preview(self):
        self.data['units'][0].pop('prompt_zh')
        errors, warnings = board.validate(self.data, self.base)
        self.assertFalse(errors)
        self.assertTrue(warnings)
        self.assertTrue(board.validate(self.data, self.base, True)[0])
        result = board.render(self.data, self.base, self.base/'看板.html', warnings)
        self.assertIn('中文镜头译文待补', result)

    def test_missing_asset_and_review_state(self):
        self.data['review_status'] = 'draft'
        self.data['references'][0]['path'] = 'missing.png'
        self.assertFalse(board.validate(self.data, self.base)[0])
        self.assertTrue(board.validate(self.data, self.base)[1])
        self.assertTrue(board.validate(self.data, self.base, True)[0])

    def test_unknown_binding_and_overflow(self):
        self.data['units'][0]['references'] = ['UNKNOWN']
        self.data['units'][0]['prompt']['summary'] += '<Picture 9>'
        self.assertGreaterEqual(len(board.validate(self.data, self.base, True)[0]), 2)

    def test_html_escape_and_template(self):
        self.data['units'][0]['prompt']['summary'] = '<script>alert("bad")</script> & 中文'
        result = board.render(self.data, self.base, self.base/'看板.html', [])
        template = (board.ASSETS/'episode-board.html').read_text(encoding='utf-8')
        for tag in ('style', 'script'):
            pattern = f'<{tag}>(.*?)</{tag}>'
            self.assertEqual(re.findall(pattern, result, re.S), re.findall(pattern, template, re.S))
        self.assertIn('&lt;script&gt;', result)
        self.assertIn('&lt;Picture 1&gt;', result)
        self.data['units'][0]['prompt_zh']['detailed_description'] += '<script>bad()</script>'
        self.assertIn('&lt;script&gt;bad()&lt;/script&gt;', board.render(self.data, self.base, self.base/'看板.html', []))
        self.assertEqual(result.count('<article '), 2)
        self.assertEqual(result.count('<details '), 2)

    def test_cli_idempotent_and_source_unchanged(self):
        source = self.base/'制作数据.json'
        source.write_text(json.dumps(self.data, ensure_ascii=False), encoding='utf-8')
        original = source.read_bytes()
        command = [sys.executable, str(Path(board.__file__)), str(source), '--final-review']
        subprocess.run(command, check=True, capture_output=True)
        output = self.base/'打开看板.html'
        stamp = output.stat().st_mtime_ns
        subprocess.run(command, check=True, capture_output=True)
        self.assertEqual(output.stat().st_mtime_ns, stamp)
        self.assertEqual(source.read_bytes(), original)

    def test_create_project_skill_also_creates_per_drama_launcher(self):
        import create_project_skill as cps
        master = self.base / '.agents/skills/h3-storyboard-director/SKILL.md'
        master.parent.mkdir(parents=True)
        master.write_text('# master', encoding='utf-8')
        skill, created = cps.create(self.base, '新作品测试', genre='都市')
        launcher = self.base / '新作品测试/启动制作看板.cmd'
        self.assertTrue(created)
        self.assertTrue(skill.is_file())
        self.assertTrue(launcher.is_file())
        text = launcher.read_text(encoding='utf-8')
        self.assertIn('--project "新作品测试"', text)
        # Re-running preserves customized launcher and regenerates if missing.
        launcher.write_text('custom launcher', encoding='utf-8')
        _, created_again = cps.create(self.base, '新作品测试')
        self.assertFalse(created_again)
        self.assertEqual(launcher.read_text(encoding='utf-8'), 'custom launcher')
        launcher.unlink()
        cps.create(self.base, '新作品测试')
        self.assertTrue(launcher.is_file())

    def test_thrill_plan_and_multi_model_anti_bland_gates(self):
        data = deepcopy(self.data)
        data['thrill_plan'] = dict(
            opening_hook_3s='0–3秒大姨猛拍木桌震飞纸符，指鼻逼退钱',
            core_pain_point='当众被骂大骗子，摊位被砸场',
            payoff_climax='掀出肩后偷笑瘦诡，林昊揣囊反赌双倍立威',
            thrill_level=9,
            slice_highlight='名场面W01：大姨拍桌逼视 vs 林昊反赌金句“明天肩还重，退你双倍！”',
            ending_hook='瘦诡趴在肩后冲镜头诡异偷笑步入暗影'
        )
        for u in data['units']:
            u['dramatic_arc'] = '拍桌指鼻施压 → 掀出肩后瘦诡加码 → 揣囊立威反赌断钩'
        data['units'][0]['dialogue'] = ['林昊：明天肩还重，退你双倍！']
        self.assertEqual(board.validate(data, self.base, True), ([], []))
        rendered = board.render(data, self.base, self.base / '看板.html', [])
        self.assertIn('前3秒痛点钩', rendered)
        self.assertIn('切片名场面与金句', rendered)
        self.assertIn('三拍爆点弧线', rendered)

        # Missing golden line after model switch is caught
        broken_gold = deepcopy(data)
        broken_gold['units'][0]['dialogue'] = ['林昊：好的我知道了。']
        errs, _ = board.validate(broken_gold, self.base, True)
        self.assertTrue(any('跨模型爆点丢失' in e for e in errs))

        # Weak micro-expression without externalized action is caught
        bland_action = deepcopy(data)
        bland_action['units'][0]['action'] = '林昊眼神微冷，嘴角微动，手指轻轻攥着衣角站在原地。'
        errs, _ = board.validate(bland_action, self.base, True)
        self.assertTrue(any('微表情站桩' in e for e in errs))

        # Seedance 2.0 (15s) header fat & dialogue overload checks
        sd_data = deepcopy(data)
        sd_data['active_model'] = 'seedance2'
        sd_data['seedance_groups'] = [dict(
            id='DB01', title='15秒爆点测试', source_locator='原件第1段', model='seedance2', duration_s=15,
            scene='公园摊位', framing='特写急摇接同轴中景',
            dramatic_arc='拍桌暴击起手 → 指鼻逼退加压 → 揣囊反杀立威',
            action='画左大姨猛拍桌面震飞纸符，探身指鼻怒骂；画右林昊扣囊反赌。',
            camera='桌面极特写顺手势急速上摇，同轴硬切中景',
            sound='拍桌脆响与原声怒喝', continuity='接下段离场背影',
            directing_summary='大姨拍桌逼退钱，林昊揣囊立赌“明天肩还重，退你双倍！”',
            references=['C01'], dialogue=['林昊：明天肩还重，退你双倍！'],
            shots=[dict(number=1, start_s=0, end_s=15, description='画左大姨猛拍木桌震起纸符，画右林昊扣囊反杀。')],
            dialogue_events=[dict(start_s=1, end_s=5, speaker='林昊', performance='冷笑有力', line='明天肩还重，退你双倍！', text='明天肩还重，退你双倍！')],
            prompt_text='15秒，16:9，都市民俗爽剧。@图片1林昊，共用树荫散射日光与接触阴影。\n0–15秒。极特写拍桌顺手势急摇中景！画左大姨猛拍木桌震飞纸符，画右林昊扣囊反杀：“明天肩还重，退你双倍！”'
        )]
        self.assertEqual(board.validate(sd_data, self.base, True), ([], []))

        # Fat header (>95 chars before 0–15秒) on SD2.0 is rejected
        fat_sd = deepcopy(sd_data)
        fat_sd['seedance_groups'][0]['prompt_text'] = ('15秒，16:9，极其冗长的BJD半写实材质说明书，轻微皮下散射，自然肤色变化，低对比度皮肤纹理，虹膜角膜高光，桌脚和马扎分别落下清晰接触阴影，画左砖道画右木桌静态站位罗列超过九十五个字的冗余头部说明。\n'
                                                       '0–15秒。极特写拍桌！林昊：“明天肩还重，退你双倍！”')
        errs, _ = board.validate(fat_sd, self.base, True)
        self.assertTrue(any('提示词头部超过95字' in e for e in errs))

        # Dialogue overload (>45 spoken chars in 15s) on SD2.0 is rejected
        chatty_sd = deepcopy(sd_data)
        long_line = '明天要是你回家之后还是觉得肩膀沉重不舒服的话，我林昊一定当着大家的面把这笔钱双倍退还给你，绝对不会赖账的！'
        chatty_sd['seedance_groups'][0]['dialogue_events'][0]['line'] = long_line
        chatty_sd['seedance_groups'][0]['dialogue_events'][0]['text'] = long_line
        chatty_sd['seedance_groups'][0]['prompt_text'] += long_line
        errs, _ = board.validate(chatty_sd, self.base, True)
        self.assertTrue(any('台词总字数超标' in e for e in errs))

    def test_condensed_thrill_dialogue_unblocked_by_default(self):
        (self.base / '原件.txt').write_text('甲说：“其实今天天气不错，你听我慢慢跟你解释清楚门到底在什么地方好不好？”', encoding='utf-8')
        data = deepcopy(self.data)
        data['active_model'] = 'seedance2'
        data['thrill_plan'] = dict(
            opening_hook_3s='拍案逼问', core_pain_point='受阻', payoff_climax='一语反杀',
            thrill_level=8, slice_highlight='金句“门在哪，说！”', ending_hook='破门而出'
        )
        data['source_quote_manifest'] = {'1': '其实今天天气不错，你听我慢慢跟你解释清楚门到底在什么地方好不好？'}
        data['source_quote_classification'] = {'spoken': [1], 'nonspoken': []}
        data['seedance_groups'] = [dict(
            id='DB01', title='脱水台词测试', source_locator='原件全文', model='seedance2', duration_s=15,
            scene='室内', framing='近景硬切', dramatic_arc='拍桌逼问 → 扣腕加压 → 一语反杀',
            action='画左甲猛拍桌面扣腕逼视。', camera='极特写硬切仰拍近景', sound='拍桌声',
            continuity='接下段', directing_summary='甲拍桌扣腕逼问“门在哪，说！”',
            references=['C01'], dialogue=['甲：门在哪，说！'],
            shots=[dict(number=1, start_s=0, end_s=15, description='画左甲猛拍桌面扣腕逼视。')],
            dialogue_events=[dict(start_s=1, end_s=3, speaker='甲', performance='冷厉短促', source_quote='1', line='门在哪，说！', text='门在哪，说！')],
            prompt_text='15秒，16:9，爽剧。@图片1甲，共用室内光。\n0–15秒。极特写拍桌硬切近景！甲拍桌扣腕逼问：“门在哪，说！”'
        )]
        # Allowed when thrill_plan is active (default short-drama condensation)
        self.assertEqual(board.validate(data, self.base, True), ([], []))
        # Blocked only when strict_verbatim=True is explicitly requested
        data['strict_verbatim'] = True
        errs, _ = board.validate(data, self.base, True)
        self.assertTrue(any('对白缺失、重复或分句改字' in e for e in errs))

    def test_custom_style_presets_and_project_skill_prompt(self):
        import create_project_skill as cps
        data = deepcopy(self.data)
        data['style_name'] = '2D厚涂韩漫'
        data['style'] = '高清商业条漫厚涂赛璐璐画风，干净线稿与强对比光影。'
        rendered = board.render(data, self.base, self.base / '看板.html', [])
        self.assertIn('<span class="tag">2D厚涂韩漫</span>', rendered)
        self.assertIn('[2D厚涂韩漫] 高清商业条漫厚涂赛璐璐画风', rendered)
        self.assertNotIn('<span class="tag">r2混合媒介</span>', rendered)

        master = self.base / '.agents/skills/h3-storyboard-director/SKILL.md'
        master.parent.mkdir(parents=True, exist_ok=True)
        master.write_text('# master', encoding='utf-8')
        skill_ask, _ = cps.create(self.base, '未选画风测试')
        self.assertIn('画风尚未指定（建剧必问用户确认）', skill_ask.read_text(encoding='utf-8'))
        skill_s2, _ = cps.create(self.base, '韩漫测试', genre='都市', style='S2')
        self.assertIn('已锁定画风 `2D厚涂韩漫`', skill_s2.read_text(encoding='utf-8'))
        skill_custom, _ = cps.create(self.base, '自定义测试', style='美式硬核暗黑美漫，粗犷阴影与红黑双色调', style_name='暗黑美漫')
        self.assertIn('已锁定画风 `暗黑美漫`', skill_custom.read_text(encoding='utf-8'))

    def test_combat_anti_collapse_gates_and_board_rendering(self):
        data = deepcopy(self.data)
        data['active_model'] = 'seedance2'
        data['thrill_plan'] = dict(
            opening_hook_3s='0–3秒反派劈门而入',
            core_pain_point='主角被逼退至柜台角',
            payoff_climax='一刀震碎木桌反杀震退对手',
            thrill_level=9,
            slice_highlight='金句“滚出去！”',
            ending_hook='敌方援兵破窗围堵'
        )
        base_group = dict(
            id='DB_COMBAT', title='当铺近身斩杀', source_locator='原件打戏段', model='seedance2', duration_s=15,
            scene='当铺大堂', framing='中全景立位硬切特写',
            dramatic_arc='破门压迫 → 格挡顿帧 → 反杀撞碎木桌',
            combat_mode='melee',
            combat_axis='起态：林昊画左(右手持横刀) ⇄ 反派画右(空手) ｜ 换位：无换位',
            action='画左林昊右手持刀硬挡反派重拳，接触瞬间火星炸开，随即反手一脚将画右反派震退撞碎木桌。',
            camera='中全景确立双方站位，动中硬切兵刃接触特写，接低仰拍撞碎木桌飞退。',
            sound='刀锋破风、金铁交鸣脆响、木桌炸裂与烟尘落定死寂。',
            continuity='林昊持刀收势喘息，反派倒在碎木中。',
            directing_summary='林昊硬挡重拳爆出火星，反脚震退反派撞碎木桌喝出“滚出去！”',
            references=['C01'], dialogue=['林昊：滚出去！'],
            shots=[
                dict(number=1, start_s=0, end_s=5, description='中全景画左林昊持刀立位迎击画右突进的反派。'),
                dict(number=2, start_s=5, end_s=10, description='动中硬切接触特写，短暂停顿火星炸开，震退对手撞碎木桌。'),
                dict(number=3, start_s=10, end_s=15, description='低仰拍烟尘中林昊喝出：“滚出去！”')
            ],
            dialogue_events=[dict(start_s=11, end_s=13, speaker='林昊', performance='冷喝', line='滚出去！', text='滚出去！')],
            prompt_text='15秒，16:9，高燃动作爽剧。@图片1林昊，共用冷暖逆光。\n0–15秒。中全景画左林昊持刀迎击，硬切特写火星炸开，震退对手撞碎木桌：“滚出去！”'
        )
        data['seedance_groups'] = [base_group]
        self.assertEqual(board.validate(data, self.base, True), ([], []))
        rendered = board.render(data, self.base, self.base / '看板.html', [])
        self.assertIn('⚔️ 近身格斗 / 冷兵器拆招', rendered)
        self.assertIn('🧭 起态：林昊画左(右手持横刀)', rendered)

        # Missing combat_axis
        no_axis = deepcopy(data)
        no_axis['seedance_groups'][0].pop('combat_axis')
        errs, _ = board.validate(no_axis, self.base, True)
        self.assertTrue(any('combat_axis' in e for e in errs))

        # Hazard phrase detected
        hazard = deepcopy(data)
        hazard['seedance_groups'][0]['action'] = '双方拳影如雨连续交手，伴随激烈打斗声撞碎木桌。'
        errs, _ = board.validate(hazard, self.base, True)
        self.assertTrue(any('打戏高危崩坏词' in e for e in errs))

        # Shot density cap (>4 shots for 15s SD2.0 combat)
        too_many_shots = deepcopy(data)
        too_many_shots['seedance_groups'][0]['shots'] = [
            dict(number=i, start_s=(i - 1) * 3, end_s=i * 3, description='击飞撞碎木桌。') for i in range(1, 6)
        ]
        errs, _ = board.validate(too_many_shots, self.base, True)
        self.assertTrue(any('最多4个镜头' in e for e in errs))

        # Missing physical impact feedback
        no_impact = deepcopy(data)
        no_impact['seedance_groups'][0]['action'] = '画左林昊持刀与画右反派摆出对峙架势挥动武器。'
        for s in no_impact['seedance_groups'][0]['shots']:
            s['description'] = '林昊在画左挥刀对峙反派。'
        no_impact['seedance_groups'][0]['prompt_text'] = '15秒，16:9，高燃动作。@图片1林昊。\n0–15秒。画左林昊挥刀对峙：“滚出去！”'
        errs, _ = board.validate(no_impact, self.base, True)
        self.assertTrue(any('受击物理反馈' in e for e in errs))


if __name__ == '__main__':
    unittest.main()

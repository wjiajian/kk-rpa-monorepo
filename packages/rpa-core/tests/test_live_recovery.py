from types import SimpleNamespace as NS
import pytest
from rpa_core.drission_browser import DrissionBrowserActions
from rpa_core.browser import ElementSpec, Locator, ScopeLocator, ElementLookupError
from rpa_core.elements import override_element_locators

class Node:
    _type = 'ChromiumElement'
    def __init__(self, number, tag='button', text='go', attrs=None):
        self._backend_id = number
        self.tag, self.raw = tag, text
        self.attrs = attrs or {}
        self.value = ''
        self.states = NS(is_alive=True, is_clickable=True, is_displayed=True, is_enabled=True, is_covered=False, is_checked=False)
        self.wait = NS(stop_moving=lambda **kw: True)
        self.scroll = NS(to_see=lambda: None, down=lambda pixels: None)
        self.rect = NS(location=(0, 0), size=(20, 20))
        self.clicks = 0
        self.click = self._click
        self.children_nodes = []
        self.xpath = f'/html/body/{tag}[{number}]'
        self.css_path = f'#{number}'
    def _click(self, **kw):
        self.clicks += 1
        return True
    def attr(self, name): return self.attrs.get(name)
    def property(self, name): return self.raw
    def eles(self, locator, timeout):
        assert timeout == 0
        return self.children_nodes
    def clear(self, **kw): self.value = ''
    def focus(self): pass
    def input(self, value, **kw): self.value += value
    def over(self, **kw): return self.cover
    def check(self, uncheck, by_js): self.states.is_checked = not uncheck

class Page:
    def __init__(self, nodes):
        self.nodes = nodes
        self.doc_ele = Node(10000, 'html')
        self.url = 'https://business.test'
    def eles(self, locator, timeout):
        assert timeout == 0
        return self.nodes.get(locator, [])

@pytest.fixture
def setup(tmp_path):
    node = Node(1, 'input', '', {'id': 'q'})
    page = Page({'css:input': [node]})
    browser = DrissionBrowserActions(page, tmp_path)
    elements = {'field': ElementSpec('field', 'field', 'page', locator=Locator('css:input'))}
    return browser, page, node, elements

def test_query_counts_full_set_paginates_and_reuses_live_objects(setup):
    b,p,n,e = setup
    p.nodes['many'] = [Node(i) for i in range(600)]
    first = b.recovery_query({'locator':'many', 'limit':3}, e)
    assert first['count'] == 600 and first['next_offset'] == 3
    again = b.recovery_query({'locator':'many', 'limit':3}, e)
    assert [r['target'] for r in first['nodes']] == [r['target'] for r in again['nodes']]
    last = b.recovery_query({'locator':'many', 'offset':599, 'limit':3}, e)
    assert len(last['nodes']) == 1 and not last['truncated']
    assert b.recovery_query({'locator':'missing'}, e)['count'] == 0

def test_field_observe_does_not_query_children_and_input_reads_value(setup):
    b,p,n,e = setup
    n.eles = lambda *a, **kw: pytest.fail('precise observe must not enumerate descendants')
    r = b.recovery_observe({'target':'field','fields':['value','text']}, e)
    assert r['value'] == r['text'] == ''
    result = b.recovery_act({'operation':'input','target':r['target'],'value':'abc',
        'expect':{'property':'value','equals':'abc'},'read':['value','text']}, e)
    assert result['issued'] and result['condition_met']
    assert result['state'] == {'value':'abc','text':''}

def test_recycled_node_detached_node_and_new_document_never_click(setup):
    b,p,n,e = setup
    target = b.recovery_query({'locator':'css:input'},e)['nodes'][0]['target']
    n.attrs['data-row-id'] = 'different-row'
    result = b.recovery_act({'operation':'click','target':target},e)
    assert not result['issued'] and 'target_changed' in result['error']
    fresh = b.recovery_query({'locator':'css:input'},e)['nodes'][0]['target']
    assert fresh != target
    n.states.is_alive=False
    assert not b.recovery_act({'operation':'click','target':fresh},e)['issued']
    n.states.is_alive=True
    p.doc_ele=Node(20000)
    assert not b.recovery_act({'operation':'click','target':fresh},e)['issued']
    assert n.clicks == 0

def test_ambiguous_formal_target_rejected_and_cover_returned(setup):
    b,p,n,e = setup
    p.nodes['css:input'].append(Node(2))
    with pytest.raises(ElementLookupError, match='found 2'):
        b.recovery_observe({'target':'field'},e)
    p.nodes['css:input'].pop()
    n.states.is_covered=9
    n.cover=Node(9, text='overlay')
    result=b.recovery_act({'operation':'click','target':'field'},e)
    assert result['error']=='covered' and result['cover'] and not result['issued']
    assert n.clicks==0

def test_wait_returns_last_value_without_repeating_action_and_cancels(setup):
    b,p,n,e=setup
    result=b.recovery_act({'operation':'click','target':'field','seconds':0.1,
        'expect':{'property':'value','equals':'never'}},e)
    assert result['issued'] and result['condition_met'] is False and result['phase']=='wait'
    assert result['actual']=='' and n.clicks==1
    calls=[]
    def check():
        calls.append(True)
        if len(calls)>3: raise ValueError('stopped')
    with pytest.raises(ValueError,match='stopped'):
        b.recovery_act({'operation':'wait','seconds':15},e,check)

def test_query_wait_absence_and_password_redaction(setup):
    b,p,n,e=setup
    assert b.recovery_act({'operation':'wait','expect':{'query':'missing','property':'exists','equals':False}},e)['condition_met']
    n.attrs['type']='password'; n.value='secret'
    assert b.recovery_observe({'target':'field','fields':['value','attrs']},e)['value']=='<redacted>'

def test_scope_path_roundtrip_and_unique_override_validation(setup):
    b,p,n,e=setup
    frame=Page({'css:input':[n]})
    shadow=Page({'css:input':[n]})
    host=NS(shadow_root=shadow)
    frame.ele=lambda loc,timeout: host
    p.get_frame=lambda loc,timeout: frame
    changes={'field':{'scope_path':[{'kind':'frame','locator':'#outer'},{'kind':'shadow','locator':'#host'}]}}
    spec=override_element_locators(e,changes)['field']
    assert b._scope(spec,timeout=0) is shadow
    assert len(spec.scope_path)==2
    with pytest.raises(ValueError):
        override_element_locators(e,{'field':{'frame':'#a','scope_path':changes['field']['scope_path']}})
    with pytest.raises(ElementLookupError,match='evidence'):
        b.validate_recovery_overrides(e,{'field':{'locator':'css:input'}})
    b.recovery_query({'locator':'css:input'},e)
    assert b.validate_recovery_overrides(e,{'field':{'locator':'css:input'}})['field'].id=='field'

class Frame(Node):
    _type = 'ChromiumFrame'
    def __init__(self, number, parent):
        super().__init__(number, 'iframe', '')
        self._target_page = parent
        self.doc_ele = Node(number + 1000, 'html')
        self.mapping = {}
    def eles(self, locator, timeout): return self.mapping.get(locator, [])

class Shadow(Node):
    _type = 'ShadowRoot'


def test_nested_frames_scope_roundtrip_and_frame_reload_invalidates_children(setup):
    b,p,n,e=setup
    outer=Frame(20,p); inner=Frame(30,outer)
    outer.mapping={'inner':[inner]}; inner.mapping={'input':[n]}
    p.nodes['outer']=[outer]
    first=b.recovery_query({'locator':'outer'},e)['nodes'][0]['target']
    second=b.recovery_query({'scope':first,'locator':'inner'},e)['nodes'][0]['target']
    child=b.recovery_query({'scope':second,'locator':'input'},e)['nodes'][0]['target']
    assert b.recovery_query({'scope':child,'relation':'document'},e)['scope']==second
    observed=b.recovery_observe({'target':child,'include_locators':True},e)
    assert [x['locator'] for x in observed['scope_path']]==['xpath:'+outer.xpath,'xpath:'+inner.xpath]
    inner.doc_ele=Node(9000,'html')
    result=b.recovery_act({'operation':'click','target':child},e)
    assert not result['issued'] and 'frame document changed' in result['error']
    new_scope=b.recovery_query({'scope':first,'locator':'inner'},e)['nodes'][0]['target']
    assert new_scope!=second


def test_shadow_root_navigation_and_unavailable_root_are_explicit(setup):
    b,p,n,e=setup
    host=Node(50,'div','')
    root=Shadow(51)
    root.children_nodes=[n]
    host.shadow_root=root
    p.nodes['host']=[host]
    host_ref=b.recovery_query({'locator':'host'},e)['nodes'][0]['target']
    scope=b.recovery_query({'scope':host_ref,'relation':'shadow'},e)['nodes'][0]['target']
    child=b.recovery_query({'scope':scope,'locator':'css:input'},e)['nodes'][0]['target']
    observed=b.recovery_observe({'target':child,'include_locators':True},e)
    assert observed['scope']==scope
    assert observed['scope_path']==[{'kind':'shadow','locator':'css:'+host.css_path}]
    root.states.is_alive=False
    assert not b.recovery_act({'operation':'click','target':child},e)['issued']
    host.shadow_root=None
    assert b.recovery_query({'scope':host_ref,'relation':'shadow'},e)['count']==0


def test_native_select_check_hover_scroll_and_key(setup):
    b,p,n,e=setup
    n.tag='select'
    n.select=NS(by_text=lambda text,timeout: setattr(n,'value',text))
    result=b.recovery_act({'operation':'select','target':'field','value':'option','read':['value']},e)
    assert result['state']['value']=='option'
    result=b.recovery_act({'operation':'check','target':'field','checked':True,'read':['checked']},e)
    assert result['state']['checked']
    n.hover=lambda: None
    assert b.recovery_act({'operation':'hover','target':'field'},e)['phase']=='complete'
    assert b.recovery_act({'operation':'scroll','target':'field'},e)['phase']=='complete'
    assert b.recovery_act({'operation':'key','target':'field','value':'ENTER'},e)['phase']=='complete'


def test_click_opens_new_tab_between_action_and_wait_is_not_missed(setup):
    b,p,n,e=setup
    new=Page({}); new.url='https://business.test/new'
    tabs=['old']; p.browser=NS(tab_ids=tabs,get_tab=lambda tab_id:new)
    n.click=lambda **kw: tabs.append('new') or True
    result=b.recovery_act({'operation':'new_tab','target':'field'},e)
    assert result['issued'] and result['condition_met'] and result['actual']==['new']
    assert b.tab is new and not b._live


def test_download_listener_is_armed_before_single_click_and_finishes_in_same_call(setup, tmp_path):
    b,p,n,e=setup
    target=tmp_path/'report.xlsx'; target.write_bytes(b'downloaded')
    flags={}; order=[]
    manager=NS(set_flag=lambda tid,value: flags.__setitem__(tid,value),get_flag=lambda tid:flags.get(tid))
    p.tab_id='tab'; p.browser=NS(_dl_mgr=manager)
    p.set=NS(when_download_file_exists=lambda value:None,download_path=lambda path:order.append('path'),download_file_name=lambda name:None)
    b.download_dir=tmp_path
    mission=NS(is_done=True,state='completed',final_path=str(target))
    def click(**kwargs):
        assert flags['tab'] is True
        order.append('click'); flags['tab']=mission
        return True
    n.click=click
    result=b.recovery_act({'operation':'download','target':'field','filename':'report.xlsx'},e)
    assert result['phase']=='complete' and result['download']['path']==str(target)
    assert order==['path','click'] and flags['tab'] is None


def test_ambiguous_frame_path_cannot_resolve_formal_id(setup):
    b,p,n,e=setup
    e['field']=ElementSpec('field','field','page',locator=Locator('css:input'),frame_locator=Locator('frames'))
    p.nodes['frames']=[Frame(2,p),Frame(3,p)]
    with pytest.raises(ElementLookupError,match='scope requires exactly one match'):
        b.recovery_observe({'target':'field'},e)


def test_temporary_reference_namespace_cannot_shadow_a_formal_element_id(setup):
    b,p,n,e=setup
    another=Node(2)
    p.nodes['other']=[another]
    e['e1']=ElementSpec('e1','formal','page',locator=Locator('other'))
    discovered=b.recovery_query({'locator':'css:input'},e)['nodes'][0]['target']
    assert discovered.startswith('@')
    result=b.recovery_act({'operation':'click','target':'e1'},e)
    assert result['phase']=='complete' and another.clicks==1 and n.clicks==0


def test_invalid_wait_or_read_contract_is_rejected_before_click(setup):
    b,p,n,e=setup
    for extra in ({'expect':{'property':'unknown','equals':True}}, {'read':['unknown']}):
        result=b.recovery_act({'operation':'click','target':'field',**extra},e)
        assert not result['issued'] and result['phase']=='precondition'
    assert n.clicks==0


def test_reference_from_an_ended_adapter_cannot_alias_new_session_object(setup, tmp_path):
    b,p,n,e=setup
    old=b.recovery_query({'locator':'css:input'},e)['nodes'][0]['target']
    b.release_recovery()
    fresh=DrissionBrowserActions(p,tmp_path)
    current=fresh.recovery_query({'locator':'css:input'},e)['nodes'][0]['target']
    assert current!=old
    assert not fresh.recovery_act({'operation':'click','target':old},e)['issued']
    assert n.clicks==0

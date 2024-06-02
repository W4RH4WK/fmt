# A basic mkdocstrings handler for {fmt}.
# Copyright (c) 2012 - present, Victor Zverovich

import os
import xml.etree.ElementTree as et
from mkdocstrings.handlers.base import BaseHandler
from typing import Any, Mapping, Optional
from subprocess import CalledProcessError, PIPE, Popen, STDOUT

class Definition:
  '''A definition extracted by Doxygen.'''
  def __init__(self, name: str, kind: str):
    self.name = name
    self.kind = kind
    self.params = None
    self.members = None

# A map from Doxygen to HTML tags.
tag_map = {
  'bold': 'b',
  'emphasis': 'em',
  'computeroutput': 'code',
  'para': 'p',
  'programlisting': 'pre',
  'verbatim': 'pre'
}

# A map from Doxygen tags to text.
tag_text_map = {
  'codeline': '',
  'highlight': '',
  'sp': ' '
}

def escape_html(s: str) -> str:
  return s.replace("<", "&lt;")

def doxyxml2html(nodes: list[et.Element]):
  out = ''
  for n in nodes:
    tag = tag_map.get(n.tag)
    if not tag:
      out += tag_text_map[n.tag]
    out += '<' + tag + '>' if tag else ''
    out += '<code class="language-cpp">' if tag == 'pre' else ''
    if n.text:
      out += escape_html(n.text)
    out += doxyxml2html(n)
    out += '</code>' if tag == 'pre' else ''
    out += '</' + tag + '>' if tag else ''
    if n.tail:
      out += n.tail
  return out

def convert_template_params(node: et.Element) -> Optional[list[Definition]]:
  templateparamlist = node.find('templateparamlist')
  if templateparamlist is None:
    return None
  params = []
  for param_node in templateparamlist.findall('param'):
    name = param_node.find('declname')
    param = Definition(name.text if name is not None else '', 'param')
    param.type = param_node.find('type').text
    params.append(param)
  return params

def get_description(node: et.Element) -> list[et.Element]:
  return node.findall('briefdescription/para') + \
         node.findall('detaileddescription/para')

def normalize_type(type: str) -> str:
  type = type.replace('< ', '<').replace(' >', '>')
  return type.replace(' &', '&').replace(' *', '*')

def convert_type(type: et.Element) -> str:
  result = type.text if type.text else ''
  for ref in type:
    result += ref.text
    if ref.tail:
      result += ref.tail
  result += type.tail.strip()
  return normalize_type(result)

def convert_params(func: et.Element) -> Definition:
  params = []
  for p in func.findall('param'):
    d = Definition(p.find('declname').text, 'param')
    d.type = convert_type(p.find('type'))
    params.append(d)
  return params

def convert_return_type(d: Definition, node: et.Element) -> None:
  d.trailing_return_type = None
  if d.type == 'auto' or d.type == 'constexpr auto':
    parts = node.find('argsstring').text.split(' -> ')
    if len(parts) > 1:
      d.trailing_return_type = normalize_type(parts[1])

def render_decl(d: Definition) -> None:
  text = '<pre><code class="language-cpp">'
  if d.template_params is not None:
    text += 'template &lt;'
    text += ', '.join(
      [f'{p.type} {p.name}'.rstrip() for p in d.template_params])
    text += '&gt;\n'
  if d.kind == 'function' or d.kind == 'variable':
    text += d.type
  elif d.kind == 'typedef':
    text += 'using'
  else:
    text += d.kind
  text += ' ' + d.name
  if d.params is not None:
    params = ', '.join([f'{p.type} {p.name}' for p in d.params])
    text += '(' + escape_html(params) + ')'
    if d.trailing_return_type:
      text += '\n ' \
        if len(d.name) + len(params) + len(d.trailing_return_type) > 68 else ''
      text += ' -> ' + escape_html(d.trailing_return_type)
  elif d.kind == 'typedef':
    text += ' = ' + escape_html(d.type)
  text += ';'
  text += '</code></pre>\n'
  return text

class CxxHandler(BaseHandler):
  def __init__(self, **kwargs: Any) -> None:
    super().__init__(handler='cxx', **kwargs)

    # Run doxygen.
    cmd = ['doxygen', '-']
    doc_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    include_dir = os.path.join(os.path.dirname(doc_dir), 'include', 'fmt')
    self._ns2doxyxml = {}
    self._doxyxml_dir = 'doxyxml'
    p = Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=STDOUT)
    out, _ = p.communicate(input=r'''
        PROJECT_NAME      = fmt
        GENERATE_LATEX    = NO
        GENERATE_MAN      = NO
        GENERATE_RTF      = NO
        CASE_SENSE_NAMES  = NO
        INPUT             = {0}/args.h {0}/base.h {0}/chrono.h {0}/color.h \
                            {0}/core.h {0}/compile.h {0}/format.h {0}/os.h \
                            {0}/ostream.h {0}/printf.h {0}/ranges.h {0}/std.h \
                            {0}/xchar.h
        QUIET             = YES
        JAVADOC_AUTOBRIEF = NO
        AUTOLINK_SUPPORT  = NO
        GENERATE_HTML     = NO
        GENERATE_XML      = YES
        XML_OUTPUT        = {1}
        ALIASES           = "rst=\verbatim embed:rst"
        ALIASES          += "endrst=\endverbatim"
        MACRO_EXPANSION   = YES
        PREDEFINED        = _WIN32=1 \
                            __linux__=1 \
                            FMT_ENABLE_IF(...)= \
                            FMT_USE_VARIADIC_TEMPLATES=1 \
                            FMT_USE_RVALUE_REFERENCES=1 \
                            FMT_USE_USER_DEFINED_LITERALS=1 \
                            FMT_USE_ALIAS_TEMPLATES=1 \
                            FMT_USE_NONTYPE_TEMPLATE_ARGS=1 \
                            FMT_API= \
                            "FMT_BEGIN_NAMESPACE=namespace fmt {{" \
                            "FMT_END_NAMESPACE=}}" \
                            "FMT_STRING_ALIAS=1" \
                            "FMT_VARIADIC(...)=" \
                            "FMT_VARIADIC_W(...)=" \
                            "FMT_DOC=1"
        EXCLUDE_SYMBOLS   = fmt::formatter fmt::printf_formatter fmt::arg_join \
                            fmt::basic_format_arg::handle
        '''.format(include_dir, self._doxyxml_dir).encode('utf-8'))
    if p.returncode != 0:
        raise CalledProcessError(p.returncode, cmd)

  def collect(self, identifier: str, config: Mapping[str, Any]) -> Definition:
    qual_name = 'fmt::' + identifier

    param_str = None
    paren = qual_name.find('(')
    if paren > 0:
      qual_name, param_str = qual_name[:paren], qual_name[paren + 1:-1]
    
    colons = qual_name.rfind('::')
    namespace, name = qual_name[:colons], qual_name[colons + 2:]

    # Load XML.
    doxyxml = self._ns2doxyxml.get(namespace)
    if doxyxml is None:
      path = f'namespace{namespace.replace("::", "_1_1")}.xml'
      with open(os.path.join(self._doxyxml_dir, path)) as f:
        doxyxml = et.parse(f)
        self._ns2doxyxml[namespace] = doxyxml

    nodes = doxyxml.findall(
      f"compounddef/sectiondef/memberdef/name[.='{name}']/..")
    candidates = []
    for node in nodes:
      # Process a function or a typedef.
      params = None
      kind = node.get('kind')
      if kind == 'function':
        params = convert_params(node)
        node_param_str = ', '.join([p.type for p in params])
        if param_str and param_str != node_param_str:
          candidates.append(f'{name}({node_param_str})')
          continue
      d = Definition(name, kind)
      d.type = convert_type(node.find('type'))
      d.template_params = convert_template_params(node)
      d.params = params
      convert_return_type(d, node)
      d.desc = get_description(node)
      return d
    
    # Process a compound definition such as a struct.
    cls = doxyxml.findall(f"compounddef/innerclass[.='{qual_name}']")
    if not cls:
      raise Exception(f'Cannot find {identifier}. Candidates: {candidates}')
    path = os.path.join(self._doxyxml_dir, cls[0].get('refid') + '.xml')
    with open(path) as f:
      xml = et.parse(f)
      node = xml.find('compounddef')
      d = Definition(identifier, node.get('kind'))
      d.template_params = convert_template_params(node)
      d.desc = get_description(node)
      d.members = []
      for m in node.findall('sectiondef[@kind="public-attrib"]/memberdef') + \
               node.findall('sectiondef[@kind="public-func"]/memberdef'):
        name = m.find('name').text
        # Doxygen incorrectly classifies members of private unnamed unions as
        # public members of the containing class.
        if name.endswith('_'):
          continue
        desc = get_description(m)
        if len(desc) == 0:
          continue
        kind = m.get('kind')
        member = Definition(name if name else '', kind)
        type = m.find('type').text
        member.type = type if type else ''
        if kind == 'function':
          member.params = convert_params(m)
          convert_return_type(member, m)
        member.template_params = None
        member.desc = desc
        d.members.append(member)
      return d

  def render(self, d: Definition, config: dict) -> str:
    text = '<div class="docblock">\n'
    text += render_decl(d)
    text += '<div class="docblock-desc">\n'
    text += doxyxml2html(d.desc)
    if d.members is not None:
      for m in d.members:
        text += self.render(m, config)
    text += '</div>\n'
    text += '</div>\n'
    return text

def get_handler(theme: str, custom_templates: Optional[str] = None,
                **config: Any) -> CxxHandler:
  '''Return an instance of `CxxHandler`.

  Arguments:
    theme: The theme to use when rendering contents.
    custom_templates: Directory containing custom templates.
    **config: Configuration passed to the handler.
  '''
  return CxxHandler(theme=theme, custom_templates=custom_templates)
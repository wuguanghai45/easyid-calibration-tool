"""Minimal GenICam node accessor using XML + GVCP register IO."""

from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree as ET

from gvcp.device import GvcpDevice


def _strip_namespace(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


@dataclass
class RegisterNode:
    name: str
    address: int
    length: int


class GenicamAccessor:
    """Access a subset of GenICam features used by scanner_config.py."""

    def __init__(self, device: GvcpDevice, xml_text: str) -> None:
        self.device = device
        self.xml_text = xml_text
        self._root = ET.fromstring(xml_text)
        self._registers = self._load_registers()

    def _load_registers(self) -> dict[str, RegisterNode]:
        registers: dict[str, RegisterNode] = {}
        for node in self._root.iter():
            kind = _strip_namespace(node.tag)
            if kind not in {"IntReg", "StringReg", "StructReg", "MaskedIntReg"}:
                continue
            name = node.attrib.get("Name", "")
            if not name:
                continue
            address_text = _child_text(node, "Address")
            if not address_text:
                continue
            try:
                address = int(address_text, 0)
            except ValueError:
                continue
            length_text = _child_text(node, "Length")
            length = int(length_text, 0) if length_text else 4
            registers[name] = RegisterNode(name=name, address=address, length=length)
        return registers

    def is_feature_valid(self, feature_name: str) -> bool:
        return self._find_feature_node(feature_name) is not None

    def list_feature_children(self, root_name: str) -> list[str]:
        category = self._find_feature_node(root_name)
        if category is None or _strip_namespace(category.tag) != "Category":
            return []
        children: list[str] = []
        for child in category:
            if _strip_namespace(child.tag) != "pFeature":
                continue
            if child.text:
                children.append(child.text.strip())
        return sorted(set(name for name in children if name))

    def set_enum_symbol(self, feature_name: str, symbol: str) -> bool:
        feature = self._find_feature_node(feature_name)
        if feature is None or _strip_namespace(feature.tag) != "Enumeration":
            return False
        value_node = _child_text(feature, "pValue")
        if not value_node:
            return False
        register = self._registers.get(value_node)
        if register is None:
            return False
        target_value = self._find_enum_value(feature, symbol)
        if target_value is None:
            return False
        self.device.write_register(register.address, target_value)
        return True

    def exec_command(self, feature_name: str) -> bool:
        feature = self._find_feature_node(feature_name)
        if feature is None or _strip_namespace(feature.tag) != "Command":
            return False
        value_register_name = _child_text(feature, "pValue")
        command_value_text = _child_text(feature, "CommandValue") or "1"
        if not value_register_name:
            return False
        register = self._registers.get(value_register_name)
        if register is None:
            return False
        self.device.write_register(register.address, int(command_value_text, 0))
        return True

    def _find_enum_value(self, enum_node: ET.Element, symbol: str) -> int | None:
        candidate_nodes: dict[str, ET.Element] = {}
        for node in self._root.iter():
            if _strip_namespace(node.tag) == "EnumEntry":
                name = node.attrib.get("Name", "")
                if name:
                    candidate_nodes[name] = node
        for child in enum_node:
            if _strip_namespace(child.tag) != "pEnumEntry":
                continue
            entry_name = (child.text or "").strip()
            entry = candidate_nodes.get(entry_name)
            if entry is None:
                continue
            symbolic = _child_text(entry, "Symbolic") or entry_name
            if symbolic.casefold() != symbol.casefold():
                continue
            value_text = _child_text(entry, "Value")
            if value_text is None:
                continue
            return int(value_text, 0)
        return None

    def _find_feature_node(self, feature_name: str) -> ET.Element | None:
        for node in self._root.iter():
            if node.attrib.get("Name") == feature_name:
                return node
        return None


def _child_text(parent: ET.Element, child_tag: str) -> str | None:
    for child in parent:
        if _strip_namespace(child.tag) == child_tag and child.text:
            return child.text.strip()
    return None


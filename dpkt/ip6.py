# $Id: ip6.py 87 2013-03-05 19:41:04Z andrewflnr@gmail.com $
# -*- coding: utf-8 -*-
"""Internet Protocol, version 6."""
from __future__ import print_function
from __future__ import absolute_import

from . import dpkt
from .decorators import deprecated
from .compat import compat_ord


class IP6(dpkt.Packet):
    """Internet Protocol, version 6.

    TODO: Longer class information....

    Attributes:
        __hdr__: Header fields of IPv6.
        TODO.
    """

    __hdr__ = (
        ('_v_fc_flow', 'I', 0x60000000),
        ('plen', 'H', 0),  # payload length (not including header)
        ('nxt', 'B', 0),  # next header protocol
        ('hlim', 'B', 0),  # hop limit
        ('src', '16s', ''),
        ('dst', '16s', '')
    )

    # XXX - to be shared with IP.  We cannot refer to the ip module
    # right now because ip.__load_protos() expects the IP6 class to be
    # defined.
    _protosw = None

    @property
    def v(self):
        return self._v_fc_flow >> 28

    @v.setter
    def v(self, v):
        self._v_fc_flow = (self._v_fc_flow & ~0xf0000000) | (v << 28)

    @property
    def fc(self):
        return (self._v_fc_flow >> 20) & 0xff

    @fc.setter
    def fc(self, v):
        self._v_fc_flow = (self._v_fc_flow & ~0xff00000) | (v << 20)

    @property
    def flow(self):
        return self._v_fc_flow & 0xfffff

    @flow.setter
    def flow(self, v):
        self._v_fc_flow = (self._v_fc_flow & ~0xfffff) | (v & 0xfffff)

    # Deprecated methods, will be removed in the future
    # =================================================
    @deprecated('v')
    def _get_v(self):
        return self.v

    @deprecated('v')
    def _set_v(self, v):
        self.v = v

    @deprecated('fc')
    def _get_fc(self):
        return self.fc

    @deprecated('fc')
    def _set_fc(self, v):
        self.fc = v

    @deprecated('flow')
    def _get_flow(self):
        return self.flow

    @deprecated('flow')
    def _set_flow(self, v):
        self.flow = v
    # =================================================

    def unpack(self, buf):
        dpkt.Packet.unpack(self, buf)
        self.extension_hdrs = {}

        if self.plen:
            buf = self.data[:self.plen]
        else:  # due to jumbo payload or TSO
            buf = self.data

        next_ext_hdr = self.nxt

        while next_ext_hdr in ext_hdrs:
            ext = ext_hdrs_cls[next_ext_hdr](buf)
            self.extension_hdrs[next_ext_hdr] = ext
            buf = buf[ext.length:]
            next_ext_hdr = getattr(ext, 'nxt', None)

        # set the payload protocol id
        if next_ext_hdr is not None:
            self.p = next_ext_hdr

        try:
            self.data = self._protosw[next_ext_hdr](buf)
            setattr(self, self.data.__class__.__name__.lower(), self.data)
        except (KeyError, dpkt.UnpackError):
            self.data = buf

    def headers_str(self):
        """Output extension headers in order defined in RFC1883 (except dest opts)"""

        header_str = b""

        for hdr in ext_hdrs:
            if hdr in self.extension_hdrs:
                header_str += bytes(self.extension_hdrs[hdr])
        return header_str

    def __bytes__(self):
        if (self.p == 6 or self.p == 17 or self.p == 58) and not self.data.sum:
            # XXX - set TCP, UDP, and ICMPv6 checksums
            p = bytes(self.data)
            s = dpkt.struct.pack('>16s16sxBH', self.src, self.dst, self.nxt, len(p))
            s = dpkt.in_cksum_add(0, s)
            s = dpkt.in_cksum_add(s, p)
            try:
                self.data.sum = dpkt.in_cksum_done(s)
            except AttributeError:
                pass
        return self.pack_hdr() + self.headers_str() + bytes(self.data)

    @classmethod
    def set_proto(cls, p, pktclass):
        cls._protosw[p] = pktclass

    @classmethod
    def get_proto(cls, p):
        return cls._protosw[p]


from . import ip
# We are most likely still in the middle of ip.__load_protos() which
# implicitly loads this module through __import__(), so the content of
# ip.IP._protosw is still incomplete at the moment.  By sharing the
# same dictionary by reference as opposed to making a copy, when
# ip.__load_protos() finishes, we will also automatically get the most
# up-to-date dictionary.
IP6._protosw = ip.IP._protosw


class IP6ExtensionHeader(dpkt.Packet):
    """
    An extension header is very similar to a 'sub-packet'.
    We just want to re-use all the hdr unpacking etc.
    """
    pass


class IP6OptsHeader(IP6ExtensionHeader):
    __hdr__ = (
        ('nxt', 'B', 0),  # next extension header protocol
        ('len', 'B', 0)  # option data length in 8 octect units (ignoring first 8 octets) so, len 0 == 64bit header
    )

    def unpack(self, buf):
        dpkt.Packet.unpack(self, buf)
        self.length = (self.len + 1) * 8
        options = []

        index = 0

        while index < self.length - 2:
            opt_type = compat_ord(self.data[index])

            # PAD1 option
            if opt_type == 0:
                index += 1
                continue

            opt_length = compat_ord(self.data[index + 1])

            if opt_type == 1:  # PADN option
                # PADN uses opt_length bytes in total
                index += opt_length + 2
                continue

            options.append(
                {'type': opt_type, 'opt_length': opt_length, 'data': self.data[index + 2:index + 2 + opt_length]})

            # add the two chars and the option_length, to move to the next option
            index += opt_length + 2

        self.options = options


class IP6HopOptsHeader(IP6OptsHeader):
    pass


class IP6DstOptsHeader(IP6OptsHeader):
    pass


class IP6RoutingHeader(IP6ExtensionHeader):
    __hdr__ = (
        ('nxt', 'B', 0),  # next extension header protocol
        ('len', 'B', 0),  # extension data length in 8 octect units (ignoring first 8 octets) (<= 46 for type 0)
        ('type', 'B', 0),  # routing type (currently, only 0 is used)
        ('segs_left', 'B', 0),  # remaining segments in route, until destination (<= 23)
        ('rsvd_sl_bits', 'I', 0),  # reserved (1 byte), strict/loose bitmap for addresses
    )

    @property
    def sl_bits(self):
        return self.rsvd_sl_bits & 0xffffff

    @sl_bits.setter
    def sl_bits(self, v):
        self.rsvd_sl_bits = (self.rsvd_sl_bits & ~0xfffff) | (v & 0xfffff)

    # Deprecated methods, will be removed in the future
    # =================================================
    @deprecated('sl_bits')
    def _get_sl_bits(self): return self.sl_bits

    @deprecated('sl_bits')
    def _set_sl_bits(self, v): self.sl_bits = v
    # =================================================

    def unpack(self, buf):
        hdr_size = 8
        addr_size = 16

        dpkt.Packet.unpack(self, buf)

        addresses = []
        num_addresses = self.len // 2
        buf = buf[hdr_size:hdr_size + num_addresses * addr_size]

        for i in range(num_addresses):
            addresses.append(buf[i * addr_size: i * addr_size + addr_size])

        self.data = buf
        self.addresses = addresses
        self.length = self.len * 8 + 8


class IP6FragmentHeader(IP6ExtensionHeader):
    __hdr__ = (
        ('nxt', 'B', 0),  # next extension header protocol
        ('resv', 'B', 0),  # reserved, set to 0
        ('frag_off_resv_m', 'H', 0),  # frag offset (13 bits), reserved zero (2 bits), More frags flag
        ('id', 'I', 0)  # fragments id
    )

    def unpack(self, buf):
        dpkt.Packet.unpack(self, buf)
        self.length = self.__hdr_len__
        self.data = b''

    @property
    def frag_off(self):
        return self.frag_off_resv_m >> 3

    @frag_off.setter
    def frag_off(self, v):
        self.frag_off_resv_m = (self.frag_off_resv_m & ~0xfff8) | (v << 3)

    @property
    def m_flag(self):
        return self.frag_off_resv_m & 1

    @m_flag.setter
    def m_flag(self, v):
        self.frag_off_resv_m = (self.frag_off_resv_m & ~0xfffe) | v

    # Deprecated methods, will be removed in the future
    # =================================================
    @deprecated('frag_off')
    def _get_frag_off(self): return self.frag_off

    @deprecated('frag_off')
    def _set_frag_off(self, v): self.frag_off = v

    @deprecated('m_flag')
    def _get_m_flag(self): return self.m_flag

    @deprecated('m_flag')
    def _set_m_flag(self, v): self.m_flag = v
    # =================================================


class IP6AHHeader(IP6ExtensionHeader):
    __hdr__ = (
        ('nxt', 'B', 0),  # next extension header protocol
        ('len', 'B', 0),  # length of header in 4 octet units (ignoring first 2 units)
        ('resv', 'H', 0),  # reserved, 2 bytes of 0
        ('spi', 'I', 0),  # SPI security parameter index
        ('seq', 'I', 0)  # sequence no.
    )

    def unpack(self, buf):
        dpkt.Packet.unpack(self, buf)
        self.length = (self.len + 2) * 4
        self.auth_data = self.data[:(self.len - 1) * 4]


class IP6ESPHeader(IP6ExtensionHeader):
    __hdr__ = (
        ('spi', 'I', 0),
        ('seq', 'I', 0)
    )

    def unpack(self, buf):
        dpkt.Packet.unpack(self, buf)
        self.length = self.__hdr_len__ + len(self.data)


ext_hdrs = [ip.IP_PROTO_HOPOPTS, ip.IP_PROTO_ROUTING, ip.IP_PROTO_FRAGMENT, ip.IP_PROTO_AH, ip.IP_PROTO_ESP,
            ip.IP_PROTO_DSTOPTS]
ext_hdrs_cls = {ip.IP_PROTO_HOPOPTS: IP6HopOptsHeader,
                ip.IP_PROTO_ROUTING: IP6RoutingHeader,
                ip.IP_PROTO_FRAGMENT: IP6FragmentHeader,
                ip.IP_PROTO_ESP: IP6ESPHeader,
                ip.IP_PROTO_AH: IP6AHHeader,
                ip.IP_PROTO_DSTOPTS: IP6DstOptsHeader}


def test_ipg():
    s = b'`\x00\x00\x00\x00(\x06@\xfe\x80\x00\x00\x00\x00\x00\x00\x02\x11$\xff\xfe\x8c\x11\xde\xfe\x80\x00\x00\x00\x00\x00\x00\x02\xb0\xd0\xff\xfe\xe1\x80r\xcd\xca\x00\x16\x04\x84F\xd5\x00\x00\x00\x00\xa0\x02\xff\xff\xf8\t\x00\x00\x02\x04\x05\xa0\x01\x03\x03\x00\x01\x01\x08\n}\x185?\x00\x00\x00\x00'
    _ip = IP6(s)
    # print `ip`
    _ip.data.sum = 0
    s2 = bytes(_ip)
    IP6(s)
    # print `ip2`
    assert (s == s2)


def test_ip6_routing_header():
    s = b'`\x00\x00\x00\x00<+@ H\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xde\xca G\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xca\xfe\x06\x04\x00\x02\x00\x00\x00\x00 \x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xde\xca "\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xde\xca\x00\x14\x00P\x00\x00\x00\x00\x00\x00\x00\x00P\x02 \x00\x91\x7f\x00\x00'
    ip = IP6(s)
    s2 = bytes(ip)
    # 43 is Routing header id
    assert (len(ip.extension_hdrs[43].addresses) == 2)
    assert ip.tcp
    assert (s == s2)
    assert bytes(ip) == s


def test_ip6_fragment_header():
    s = b'\x06\xee\xff\xfb\x00\x00\xff\xff'
    fh = IP6FragmentHeader(s)
    # s2 = str(fh) variable 's2' is not used
    bytes(fh)
    assert (fh.nxt == 6)
    assert (fh.id == 65535)
    assert (fh.frag_off == 8191)
    assert (fh.m_flag == 1)
    assert bytes(fh) == s

    # IP6 with fragment header
    s = b'\x60\x00\x00\x00\x00\x10\x2c\x00\x02\x22\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x03\x33\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x03\x29\x00\x00\x01\x00\x00\x00\x00\x60\x00\x00\x00\x00\x10\x2c\x00'
    ip = IP6(s)
    assert bytes(ip) == s


def test_ip6_options_header():
    s = b';\x04\x01\x02\x00\x00\xc9\x10\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\xc2\x04\x00\x00\x00\x00\x05\x02\x00\x00\x01\x02\x00\x00'
    options = IP6OptsHeader(s).options
    assert (len(options) == 3)
    assert bytes(IP6OptsHeader(s)) == s


def test_ip6_ah_header():
    s = b';\x04\x00\x00\x02\x02\x02\x02\x01\x01\x01\x01\x78\x78\x78\x78\x78\x78\x78\x78'
    ah = IP6AHHeader(s)
    assert (ah.length == 24)
    assert (ah.auth_data == b'xxxxxxxx')
    assert (ah.spi == 0x2020202)
    assert (ah.seq == 0x1010101)
    assert bytes(ah) == s


def test_ip6_esp_header():
    s = b'\x00\x00\x01\x00\x00\x00\x00\x44\xe2\x4f\x9e\x68\xf3\xcd\xb1\x5f\x61\x65\x42\x8b\x78\x0b\x4a\xfd\x13\xf0\x15\x98\xf5\x55\x16\xa8\x12\xb3\xb8\x4d\xbc\x16\xb2\x14\xbe\x3d\xf9\x96\xd4\xa0\x39\x1f\x85\x74\x25\x81\x83\xa6\x0d\x99\xb6\xba\xa3\xcc\xb6\xe0\x9a\x78\xee\xf2\xaf\x9a'
    esp = IP6ESPHeader(s)
    assert esp.length == 68
    assert esp.spi == 256
    assert bytes(esp) == s


def test_ip6_extension_headers():
    p = b'`\x00\x00\x00\x00<+@ H\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xde\xca G\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xca\xfe\x06\x04\x00\x02\x00\x00\x00\x00 \x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xde\xca "\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xde\xca\x00\x14\x00P\x00\x00\x00\x00\x00\x00\x00\x00P\x02 \x00\x91\x7f\x00\x00'
    ip = IP6(p)
    o = b';\x04\x01\x02\x00\x00\xc9\x10\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\xc2\x04\x00\x00\x00\x00\x05\x02\x00\x00\x01\x02\x00\x00'
    options = IP6HopOptsHeader(o)
    ip.extension_hdrs[0] = options
    fh = b'\x06\xee\xff\xfb\x00\x00\xff\xff'
    ip.extension_hdrs[44] = IP6FragmentHeader(fh)
    ah = b';\x04\x00\x00\x02\x02\x02\x02\x01\x01\x01\x01\x78\x78\x78\x78\x78\x78\x78\x78'
    ip.extension_hdrs[51] = IP6AHHeader(ah)
    do = b';\x02\x01\x02\x00\x00\xc9\x10\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
    ip.extension_hdrs[60] = IP6DstOptsHeader(do)
    assert (len(ip.extension_hdrs) == 5)


if __name__ == '__main__':
    test_ipg()
    test_ip6_routing_header()
    test_ip6_fragment_header()
    test_ip6_options_header()
    test_ip6_ah_header()
    test_ip6_esp_header()
    test_ip6_extension_headers()
    print('Tests Successful...')

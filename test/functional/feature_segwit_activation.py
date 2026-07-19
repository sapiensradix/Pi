#!/usr/bin/env python3
# Copyright (c) 2026 The Pi Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""Test the Pi mainnet-style SegWit activation boundary at height 17."""

from test_framework.blocktools import (
    add_witness_commitment,
    create_block,
    create_coinbase,
)
from test_framework.messages import (
    CTxInWitness,
    ser_uint256,
)
from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import (
    assert_equal,
    softfork_active,
)


SEGWIT_ACTIVATION_HEIGHT = 17


class SegWitActivationTest(BitcoinTestFramework):
    def set_test_params(self):
        self.setup_clean_chain = True
        self.num_nodes = 1
        self.extra_args = [[f'-testactivationheight=segwit@{SEGWIT_ACTIVATION_HEIGHT}']]

    def run_test(self):
        node = self.nodes[0]

        self.generate(node, SEGWIT_ACTIVATION_HEIGHT - 2)
        assert_equal(node.getblockcount(), 15)
        assert not softfork_active(node, 'segwit')

        self.log.info('Accept block 16 without witness data or a witness commitment')
        block16 = create_block(
            hashprev=int(node.getbestblockhash(), 16),
            coinbase=create_coinbase(16),
        )
        block16.solve()
        assert_equal(node.submitblock(block16.serialize().hex()), None)
        assert_equal(node.getblockcount(), 16)
        assert 'txinwitness' not in node.getblock(block16.hash, 2)['tx'][0]['vin'][0]
        assert softfork_active(node, 'segwit')

        self.log.info('Reject block 17 with witness data but no witness commitment')
        block17_missing_commitment = create_block(
            hashprev=block16.sha256,
            coinbase=create_coinbase(17),
            ntime=block16.nTime + 1,
        )
        block17_missing_commitment.vtx[0].wit.vtxinwit = [CTxInWitness()]
        block17_missing_commitment.vtx[0].wit.vtxinwit[0].scriptWitness.stack = [ser_uint256(0)]
        block17_missing_commitment.vtx[0].rehash()
        block17_missing_commitment.hashMerkleRoot = block17_missing_commitment.calc_merkle_root()
        block17_missing_commitment.solve()
        assert_equal(
            node.submitblock(block17_missing_commitment.serialize().hex()),
            'unexpected-witness',
        )
        assert_equal(node.getblockcount(), 16)

        self.log.info('Accept block 17 with a valid witness nonce and commitment')
        block17 = create_block(
            hashprev=block16.sha256,
            coinbase=create_coinbase(17),
            ntime=block16.nTime + 2,
        )
        add_witness_commitment(block17)
        block17.solve()
        assert_equal(node.submitblock(block17.serialize().hex()), None)
        assert_equal(node.getblockcount(), 17)

        coinbase = node.getblock(block17.hash, 2)['tx'][0]
        assert_equal(len(coinbase['vin'][0]['txinwitness'][0]), 64)
        assert_equal(coinbase['vout'][-1]['scriptPubKey']['hex'][:12], '6a24aa21a9ed')


if __name__ == '__main__':
    SegWitActivationTest().main()

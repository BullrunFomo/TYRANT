import asyncio, aiohttp, base64

RPC = 'https://mainnet.helius-rpc.com/?api-key=8f782b8d-f2de-47e9-8ce2-11dea01afa2f'
PUMP = '6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P'
CREATE_V2_DISC = bytes([214, 144, 76, 236, 95, 139, 49, 180])


async def get_alt_addresses(session, alt_address: str) -> list[str]:
    """Fetch and parse an Address Lookup Table account to get its addresses list."""
    payload = {
        'jsonrpc': '2.0', 'id': 1,
        'method': 'getAccountInfo',
        'params': [alt_address, {'encoding': 'jsonParsed'}],
    }
    async with session.post(RPC, json=payload) as r:
        data = await r.json()
    result = data.get('result', {})
    if not result or not result.get('value'):
        return []
    parsed = result['value'].get('data', {})
    if isinstance(parsed, dict) and 'parsed' in parsed:
        addresses = parsed['parsed'].get('info', {}).get('addresses', [])
        return addresses
    return []


async def main():
    payload = {
        'jsonrpc': '2.0', 'id': 1,
        'method': 'getSignaturesForAddress',
        'params': [PUMP, {'limit': 50, 'commitment': 'confirmed'}]
    }
    async with aiohttp.ClientSession() as s:
        async with s.post(RPC, json=payload) as r:
            sigs = await r.json()

    for entry in sigs.get('result', []):
        sig = entry['signature']
        tx_payload = {
            'jsonrpc': '2.0', 'id': 1,
            'method': 'getTransaction',
            'params': [sig, {'encoding': 'base64', 'commitment': 'confirmed', 'maxSupportedTransactionVersion': 0}]
        }
        async with aiohttp.ClientSession() as s:
            async with s.post(RPC, json=tx_payload) as r:
                tx_resp = await r.json()

        tx_data = tx_resp.get('result')
        if not tx_data:
            continue
        raw = base64.b64decode(tx_data['transaction'][0])

        if CREATE_V2_DISC not in raw:
            continue

        print('Found create_v2 tx:', sig)

        from solders.transaction import VersionedTransaction
        tx = VersionedTransaction.from_bytes(raw)
        msg = tx.message

        static_keys = [str(k) for k in msg.account_keys]
        all_keys = list(static_keys)

        # Load ALT accounts
        if hasattr(msg, 'address_table_lookups') and msg.address_table_lookups:
            async with aiohttp.ClientSession() as s:
                for alt in msg.address_table_lookups:
                    alt_addr = str(alt.account_key)
                    print(f'  Loading ALT: {alt_addr}')
                    addresses = await get_alt_addresses(s, alt_addr)
                    print(f'  ALT has {len(addresses)} addresses')
                    writable_idxs = list(alt.writable_indexes)
                    readonly_idxs = list(alt.readonly_indexes)
                    print(f'  writable_indexes={writable_idxs}')
                    print(f'  readonly_indexes={readonly_idxs}')
                    # The order in the resolved account list is: writable first, then readonly
                    for idx in writable_idxs:
                        if idx < len(addresses):
                            all_keys.append(addresses[idx])
                    for idx in readonly_idxs:
                        if idx < len(addresses):
                            all_keys.append(addresses[idx])

        hdr = msg.header
        n_sig = hdr.num_required_signatures
        n_ro_signed = hdr.num_readonly_signed_accounts
        n_ro_unsigned = hdr.num_readonly_unsigned_accounts
        n_static = len(static_keys)

        print(f'\nAll accounts (static={n_static}, total={len(all_keys)}):')
        for i, key in enumerate(all_keys):
            if i < n_sig - n_ro_signed:
                role = 'writable-signer'
            elif i < n_sig:
                role = 'readonly-signer'
            elif i < n_static - n_ro_unsigned:
                role = 'writable'
            else:
                role = 'readonly'
            suffix = ' (ALT)' if i >= n_static else ''
            print(f'  [{i:2d}] {role:20s} {key}{suffix}')

        for ix in msg.instructions:
            prog = static_keys[ix.program_id_index]
            if str(prog) != PUMP:
                continue
            ix_data = bytes(ix.data)
            if ix_data[:8] != CREATE_V2_DISC:
                continue
            print('\nCreate V2 instruction accounts (pos -> global_idx -> pubkey):')
            for j, acc_idx in enumerate(ix.accounts):
                key = all_keys[acc_idx] if acc_idx < len(all_keys) else f'MISSING[{acc_idx}]'
                src = '(ALT)' if acc_idx >= n_static else ''
                print(f'  pos[{j:2d}] -> tx[{acc_idx:2d}] {src} = {key}')
            break
        break

asyncio.run(main())

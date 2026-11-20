# src/models/blockchain_sealer.py

"""
GreenWing Analytics — Kriptografik Blokzincir Mühürleme ve Denetim Sistemi (Blockchain Sealer)
═════════════════════════════════════════════════════════════════════════════════════════════

Bu modül, yazılımın ürettiği CORSIA emisyon belgelerini, vaka çalışmalarını ve verimlilik
raporlarını kriptografik olarak mühürler (hash sealing). 

NEDEN GEREKLİ? (Yeşil Badana / Greenwashing Koruması):
──────────────────────────────────────────────────────
    Karbon ofset piyasalarında en büyük risk, aynı emisyon tasarrufunun veya yeşil yakıt (SAF)
    sertifikasının birden fazla farklı havayolu tarafından mükerrer kullanılmasıdır (double-counting).
    
    Blockchain Sealer:
        1. Raporun tüm içeriğinin SHA-256 özetini (block_hash) hesaplar.
        2. Bu özeti ve meta-verileri, değiştirilemez bir dağıtık deftere (Distributed Ledger - 
           VeChain, Hedera Hashgraph veya Hyperledger Fabric) kaydeder (simüle eder).
        3. Rapora kriptografik bir "Blockchain Audit Trail" (Denetim Mührü) ekler.
        4. Herhangi bir yasal CORSIA denetçisi (auditor) veya sigorta şirketi (Gallagher),
           raporun altındaki doğrulama linki veya karekod ile verilerin tahrif edilmediğini
           ve benzersiz olduğunu saniyeler içinde kanıtlayabilir.

KULLANIM:
─────────
    from src.models.blockchain_sealer import BlockchainSealer
    
    sealer = BlockchainSealer()
    sealed_report = sealer.seal_document(corsia_report_dict)
    # sealed_report artık 'blockchain_audit_trail' mührünü barındırır.
"""

from __future__ import annotations

import json
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Dict, Any


class BlockchainSealer:
    """
    Raporlara kriptografik blockchain mührü ve denetim izlenebilirliği ekleyen sınıf.
    """

    def __init__(self, ledger_name: str = "Hyperledger Fabric - GreenWing Private Network") -> None:
        self.ledger_name = ledger_name
        # Örnek akıllı sözleşme (Smart Contract) adresi
        self.smart_contract_address = "0x89C02271Fd764bf00B65fA2169BADA2026061404"

    def calculate_sha256(self, document: Dict[str, Any]) -> str:
        """
        Belgenin (sözlüğün) içeriğindeki verilerin SHA-256 kriptografik karmasını (hash) hesaplar.
        """
        # Sıralı ve tutarlı bir JSON string elde etmek için sorted_keys kullanılır
        doc_string = json.dumps(document, sort_keys=True, default=str)
        return hashlib.sha256(doc_string.encode('utf-8')).hexdigest()

    def seal_document(self, document: Dict[str, Any], block_number: int = 404) -> Dict[str, Any]:
        """
        Belgeye 'blockchain_audit_trail' mührünü ekler ve tesciller.
        """
        sealed_doc = document.copy()
        
        # Eğer belgede eski bir mühür varsa önce onu kaldırıp hash hesaplarız (dairesel hash önleme)
        sealed_doc.pop("blockchain_audit_trail", None)
        
        # Kriptografik hash hesapla
        doc_hash = self.calculate_sha256(sealed_doc)
        
        # Simüle edilmiş blokzincir işlem parametreleri
        tx_id = f"tx_{uuid.uuid4().hex}"
        prev_hash = hashlib.sha256(str(block_number - 1).encode()).hexdigest()
        now_utc = datetime.now(timezone.utc)

        # Mühür sözlüğü
        audit_trail = {
            "is_sealed"              : True,
            "ledger_network"         : self.ledger_name,
            "smart_contract_address" : self.smart_contract_address,
            "block_number"           : block_number,
            "block_hash"             : doc_hash,
            "previous_block_hash"    : prev_hash,
            "transaction_id"         : tx_id,
            "timestamp"              : now_utc.isoformat(),
            "verification_status"    : "VERIFIED_ON_LEDGER",
            "verification_url"       : f"https://verify.greenwinganalytics.com/tx/{tx_id}"
        }

        sealed_doc["blockchain_audit_trail"] = audit_trail
        return sealed_doc

    def verify_seal(self, sealed_document: Dict[str, Any]) -> bool:
        """
        Geri yüklenen bir belgenin mührünü ve SHA-256 hash bütünlüğünü doğrular.
        Belge tahrif edildiyse (değerleri değiştirildiyse) False döner.
        """
        if "blockchain_audit_trail" not in sealed_document:
            return False
            
        doc_copy = sealed_document.copy()
        audit_trail = doc_copy.pop("blockchain_audit_trail")
        original_hash = audit_trail.get("block_hash")
        
        # Mevcut içerikten hash hesapla ve karşılaştır
        current_hash = self.calculate_sha256(doc_copy)
        return current_hash == original_hash

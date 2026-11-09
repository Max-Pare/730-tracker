# SPDX-License-Identifier: AGPL-3.0-or-later
"""Realistic OCR text samples (all names, codes and numbers are fictitious)."""

PHARMACY_ELECTRONIC = """\
FARMACIA SAN MARCO DR. ROSSI
Via Roma 12 - 20121 Milano MI
P.IVA 01234567897
Tel. 02 1234567
DOCUMENTO COMMERCIALE
di vendita o prestazione
DESCRIZIONE              IVA   Prezzo(€)
FARMACO                  10%      12,50
FARMACO SOP              10%       8,90
TICKET                             2,00
TOTALE COMPLESSIVO                23,40
di cui IVA                         1,95
Pagamento contante                 0,00
Pagamento elettronico             23,40
Importo pagato                    23,40
09-03-2025 10:22
DOCUMENTO N. 0123-0045
RT 99MEY012345
C.F. CLIENTE: RSSMRA80A01H501U
"""

PHARMACY_MIXED_CASH = """\
FARMACIA CENTRALE
Corso Italia 5, 10121 Torino
P. IVA 02345678904
DOCUMENTO COMMERCIALE
FARMACO OTC          10%     9,80
PARAFARMACO          22%    15,00
DISPOSITIVO MEDICO   22%     6,20
TOTALE COMPLESSIVO          31,00
Pagamento contante          50,00
Resto                       19,00
14/11/2025 18:03
Documento n. 0456-0012
Codice Fiscale RSSMRA8OA0lH5O1U
"""

DOCTOR_INVOICE = """\
Dott. Giuseppe Verdi
Medico Chirurgo - Specialista in Cardiologia
Via Garibaldi 3, 40121 Bologna
C.F. VRDGPP70C15L219C  P.IVA 03456789019

FATTURA N. 45/2025 del 21/05/2025

Spett.le
Sig.ra Laura Bianchi
C.F. BNCLRA85M41F205C

Visita cardiologica con ECG         150,00
Imposta di bollo                      2,00
TOTALE DOCUMENTO                    152,00
Pagamento: POS (carta di debito)
Operazione esente IVA art. 10 DPR 633/72
"""

TICKET_ASL = """\
ASST VALLE SERENA
Azienda Socio Sanitaria Territoriale
P.IVA 08901234560
RICEVUTA DI PAGAMENTO N. 2025/778812
Data: 03/02/2025
Assistito: RSSMRA80A01H501U
Prestazione: ECOGRAFIA ADDOME COMPLETO
Compartecipazione alla spesa (ticket)
IMPORTO PAGATO EUR 36,15
Pagato in contanti
"""

DENTIST_CASH = """\
STUDIO DENTISTICO SORRISI SRL
Viale Europa 100 - 00144 Roma
P.IVA 04567890126
RICEVUTA N. 112 del 7 ottobre 2025
Paziente: Rossi Luca CF RSSLCU12T10H501I
Igiene orale professionale (detartrasi)    80,00
Otturazione                               120,00
TOTALE                                    200,00
Pagamento in contanti
"""

OPTICIAN = """\
OTTICA BELLAVISTA S.N.C.
Piazza Duomo 1 Firenze
P.IVA 05678901231
DOCUMENTO COMMERCIALE DI VENDITA
LENTI A CONTATTO MENSILI     22%     45,00
SOLUZIONE UNICA              22%     12,00
TOTALE COMPLESSIVO                   57,00
Pagamento contante                   57,00
Pagamento elettronico                 0,00
22.08.2025 11:47
DOC. N. 0007-0331
C.F. BNCLRA85M41F205C
"""

LAB_ANALYSIS = """\
LABORATORIO ANALISI CLINICHE SALUS
Struttura accreditata SSN
P.IVA 06789012348
Fattura n. A/1520
Data emissione 15-01-2025
Intestata a: FRRGNN60B12A944C
Emocromo completo                 8,50
Glicemia                          3,20
Colesterolo totale e HDL          6,30
TOTALE FATTURA € 18,00
Pagato con Bancomat
"""

VET_CLINIC = """\
CLINICA VETERINARIA AMICI A 4 ZAMPE
Dr. Med. Vet. Anna Neri
P.IVA 07890123453
Fattura n. 88/2025 del 30/06/2025
Cliente: RSSMRA80A01H501U
Visita clinica cane "Fido"                 60,00
Vaccinazione                               35,00
TOTALE DA PAGARE                           95,00
Pagamento: carta di credito
"""

NOISY_OCR = """\
FARMAC1A DEL P0NTE
P IVA 0234 5678 904
D0CUMENT0 C0MMERCIALE
FARMAC0          10%   7 ,40
T0TALE C0MPLESSIV0     7,40
PAGAMENT0 ELETTR0NIC0  7,40
1O/12/2025 09:15
"""

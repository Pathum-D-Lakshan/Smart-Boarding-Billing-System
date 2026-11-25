"""Bounded static-PDF inspection worker. Reads bytes on stdin, never file paths."""
import sys
from io import BytesIO


def validate(data):
    from pypdf import PdfReader,overwrite_configuration
    from pypdf.generic import ArrayObject,DictionaryObject,IndirectObject,StreamObject
    # A separate short-lived process bounds parser time and isolates its state.
    limit=20*1024*1024
    overwrite_configuration(maximum_declared_stream_length=limit,array_based_stream_maximum_output_length=limit,
        zlib_maximum_output_length=limit,lzw_maximum_output_length=limit,run_length_maximum_output_length=limit,
        brotli_maximum_output_length=limit,jbig2_maximum_output_length=limit,image_maximum_buffer_size=limit,
        array_maximum_element_count=15000,dictionary_maximum_element_count=15000,stream_filters_maximum_length=4,
        stream_decoding_work_maximum_length=limit,page_tree_maximum_entries=100,page_tree_maximum_depth=20,
        page_tree_maximum_page_entries=10000,jbig2dec_binary=None)
    reader=PdfReader(BytesIO(data),strict=True)
    if reader.is_encrypted or not 1<=len(reader.pages)<=10: raise ValueError()
    forbidden={'/JS','/JavaScript','/AA','/OpenAction','/Launch','/EmbeddedFiles','/EF',
        '/AcroForm','/XFA','/RichMedia','/3D','/Movie','/Sound','/SubmitForm','/ImportData',
        '/GoToR','/GoToE','/URI','/Filespec','/Collection'}
    seen=set(); budget=[0,0]
    def walk(obj,depth=0):
        if depth>50: raise ValueError()
        if isinstance(obj,IndirectObject):
            key=(obj.idnum,obj.generation)
            if key in seen: return
            seen.add(key); obj=obj.get_object()
        budget[0]+=1
        if budget[0]>15000: raise ValueError()
        if isinstance(obj,DictionaryObject):
            if forbidden.intersection(obj.keys()): raise ValueError()
            # Even non-JavaScript actions and external resources are unnecessary
            # in static financial evidence; do not execute or embed any PDF.
            if obj.get('/S') in ('/JavaScript','/Launch','/URI','/GoToR','/SubmitForm'): raise ValueError()
            if isinstance(obj,StreamObject):
                decoded=obj.get_data(); budget[1]+=len(decoded)
                if budget[1]>20*1024*1024: raise ValueError()
            for value in obj.values(): walk(value,depth+1)
        elif isinstance(obj,ArrayObject):
            for value in obj: walk(value,depth+1)
    walk(reader.trailer)
    # Inspect unreferenced objects too; never accept hidden active payloads merely
    # because the current page tree does not reference them.
    count=sum(len(items) for items in reader.xref.values())+len(reader.xref_objStm)
    if count>5000: raise ValueError()
    for generation,items in reader.xref.items():
        for number in items:
            if number: walk(IndirectObject(number,generation,reader))
    for number in reader.xref_objStm: walk(IndirectObject(number,0,reader))
    for page in reader.pages:
        if page.mediabox.width<=0 or page.mediabox.height<=0: raise ValueError()


if __name__=='__main__':
    try:
        data=sys.stdin.buffer.read(10*1024*1024+1)
        if not data or len(data)>10*1024*1024: raise ValueError()
        validate(data)
    except Exception:
        sys.stdout.write('INVALID\n'); sys.exit(1)
    sys.stdout.write('OK\n')

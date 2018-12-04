{
    "600": {
        "name": "600.perlbench_s",
        "commands": [
            "../run_base_test_mytest-m64.0000/perlbench_s_base.mytest-m64 -I. -I./lib makerand.pl > makerand.out 2>> makerand.err",
            "../run_base_test_mytest-m64.0000/perlbench_s_base.mytest-m64 -I. -I./lib test.pl > test.out 2>> test.err",
        ],
    },
    "602": {"name": "602.gcc_s", "commands": []},
    "605": {
        "name": "605.mcf_s",
        "commands": [
            "../run_base_test_mytest-m64.0000/mcf_s_base.mytest-m64 inp.in  > inp.out 2>> inp.err"
        ],
    },
    "620": {
        "name": "620.omnetpp_s",
        "commands": [
            "../run_base_test_mytest-m64.0000/omnetpp_s_base.mytest-m64 -c General -r 0 > omnetpp.General-0.out 2>> omnetpp.General-0.err"
        ],
    },
    "623": {
        "name": "623.xalancbmk_s",
        "commands": [
            "../run_base_test_mytest-m64.0000/xalancbmk_s_base.mytest-m64 -v test.xml xalanc.xsl > test-test.out 2>> test-test.err"
        ],
    },
    "625": {
        "name": "625.x264_s",
        "commands": [
            "../run_base_test_mytest-m64.0000/x264_s_base.mytest-m64 --dumpyuv 50 --frames 156 -o BuckBunny_New.264 BuckBunny.yuv 1280x720 > run_000-156_x264_s_base.mytest-m64_x264.out 2>> run_000-156_x264_s_base.mytest-m64_x264.err"
        ],
    },
    "631": {
        "name": "631.deepsjeng_s",
        "commands": [
            "../run_base_test_mytest-m64.0000/deepsjeng_s_base.mytest-m64 test.txt > test.out 2>> test.err"
        ],
    },
    "641": {
        "name": "641.leela_s",
        "commands": [
            "../run_base_test_mytest-m64.0000/leela_s_base.mytest-m64 test.sgf > test.out 2>> test.err"
        ],
    },
    "648": {
        "name": "648.exchange2_s",
        "commands": [
            "../run_base_test_mytest-m64.0000/exchange2_s_base.mytest-m64 0 > exchange2.txt 2>> exchange2.err"
        ],
    },
    "657": {
        "name": "657.xz_s",
        "commands": [
            "../run_base_test_mytest-m64.0000/xz_s_base.mytest-m64 cpu2006docs.tar.xz 4 055ce243071129412e9dd0b3b69a21654033a9b723d874b2015c774fac1553d9713be561ca86f74e4f16f22e664fc17a79f30caa5ad2c04fbc447549c2810fae 1548636 1555348 0 > cpu2006docs.tar-4-0.out 2>> cpu2006docs.tar-4-0.err",
            "../run_base_test_mytest-m64.0000/xz_s_base.mytest-m64 cpu2006docs.tar.xz 4 055ce243071129412e9dd0b3b69a21654033a9b723d874b2015c774fac1553d9713be561ca86f74e4f16f22e664fc17a79f30caa5ad2c04fbc447549c2810fae 1462248 -1 1 > cpu2006docs.tar-4-1.out 2>> cpu2006docs.tar-4-1.err",
            "../run_base_test_mytest-m64.0000/xz_s_base.mytest-m64 cpu2006docs.tar.xz 4 055ce243071129412e9dd0b3b69a21654033a9b723d874b2015c774fac1553d9713be561ca86f74e4f16f22e664fc17a79f30caa5ad2c04fbc447549c2810fae 1428548 -1 2 > cpu2006docs.tar-4-2.out 2>> cpu2006docs.tar-4-2.err",
            "../run_base_test_mytest-m64.0000/xz_s_base.mytest-m64 cpu2006docs.tar.xz 4 055ce243071129412e9dd0b3b69a21654033a9b723d874b2015c774fac1553d9713be561ca86f74e4f16f22e664fc17a79f30caa5ad2c04fbc447549c2810fae 1034828 -1 3e > cpu2006docs.tar-4-3e.out 2>> cpu2006docs.tar-4-3e.err",
            "../run_base_test_mytest-m64.0000/xz_s_base.mytest-m64 cpu2006docs.tar.xz 4 055ce243071129412e9dd0b3b69a21654033a9b723d874b2015c774fac1553d9713be561ca86f74e4f16f22e664fc17a79f30caa5ad2c04fbc447549c2810fae 1061968 -1 4 > cpu2006docs.tar-4-4.out 2>> cpu2006docs.tar-4-4.err",
            "../run_base_test_mytest-m64.0000/xz_s_base.mytest-m64 cpu2006docs.tar.xz 4 055ce243071129412e9dd0b3b69a21654033a9b723d874b2015c774fac1553d9713be561ca86f74e4f16f22e664fc17a79f30caa5ad2c04fbc447549c2810fae 1034588 -1 4e > cpu2006docs.tar-4-4e.out 2>> cpu2006docs.tar-4-4e.err",
            "../run_base_test_mytest-m64.0000/xz_s_base.mytest-m64 cpu2006docs.tar.xz 1 055ce243071129412e9dd0b3b69a21654033a9b723d874b2015c774fac1553d9713be561ca86f74e4f16f22e664fc17a79f30caa5ad2c04fbc447549c2810fae 650156 -1 0 > cpu2006docs.tar-1-0.out 2>> cpu2006docs.tar-1-0.err",
            "../run_base_test_mytest-m64.0000/xz_s_base.mytest-m64 cpu2006docs.tar.xz 1 055ce243071129412e9dd0b3b69a21654033a9b723d874b2015c774fac1553d9713be561ca86f74e4f16f22e664fc17a79f30caa5ad2c04fbc447549c2810fae 639996 -1 1 > cpu2006docs.tar-1-1.out 2>> cpu2006docs.tar-1-1.err",
            "../run_base_test_mytest-m64.0000/xz_s_base.mytest-m64 cpu2006docs.tar.xz 1 055ce243071129412e9dd0b3b69a21654033a9b723d874b2015c774fac1553d9713be561ca86f74e4f16f22e664fc17a79f30caa5ad2c04fbc447549c2810fae 637616 -1 2 > cpu2006docs.tar-1-2.out 2>> cpu2006docs.tar-1-2.err",
            "../run_base_test_mytest-m64.0000/xz_s_base.mytest-m64 cpu2006docs.tar.xz 1 055ce243071129412e9dd0b3b69a21654033a9b723d874b2015c774fac1553d9713be561ca86f74e4f16f22e664fc17a79f30caa5ad2c04fbc447549c2810fae 628996 -1 3e > cpu2006docs.tar-1-3e.out 2>> cpu2006docs.tar-1-3e.err",
            "../run_base_test_mytest-m64.0000/xz_s_base.mytest-m64 cpu2006docs.tar.xz 1 055ce243071129412e9dd0b3b69a21654033a9b723d874b2015c774fac1553d9713be561ca86f74e4f16f22e664fc17a79f30caa5ad2c04fbc447549c2810fae 631912 -1 4 > cpu2006docs.tar-1-4.out 2>> cpu2006docs.tar-1-4.err",
            "../run_base_test_mytest-m64.0000/xz_s_base.mytest-m64 cpu2006docs.tar.xz 1 055ce243071129412e9dd0b3b69a21654033a9b723d874b2015c774fac1553d9713be561ca86f74e4f16f22e664fc17a79f30caa5ad2c04fbc447549c2810fae 629064 -1 4e > cpu2006docs.tar-1-4e.out 2>> cpu2006docs.tar-1-4e.err",
        ],
    },
    "603": {
        "name": "603.bwaves_s",
        "commands": [
            "../run_base_test_mytest-m64.0000/speed_bwaves_base.mytest-m64 bwaves_1 < bwaves_1.in > bwaves_1.out 2>> bwaves_1.err",
            "../run_base_test_mytest-m64.0000/speed_bwaves_base.mytest-m64 bwaves_2 < bwaves_2.in > bwaves_2.out 2>> bwaves_2.err",
        ],
    },
    "607": {
        "name": "607.cactuBSSN_s",
        "commands": [
            "../run_base_test_mytest-m64.0000/cactuBSSN_s_base.mytest-m64 spec_test.par   > spec_test.out 2>> spec_test.err"
        ],
    },
    "619": {
        "name": "619.lbm_s",
        "commands": [
            "../run_base_test_mytest-m64.0000/lbm_s_base.mytest-m64 20 reference.dat 0 1 200_200_260_ldc.of > lbm.out 2>> lbm.err"
        ],
    },
    "621": {
        "name": "621.wrf_s",
        "commands": [
            "../run_base_test_mytest-m64.0000/wrf_s_base.mytest-m64 > rsl.out.0000 2>> wrf.err"
        ],
    },
    "627": {
        "name": "627.cam4_s",
        "commands": [
            "../run_base_test_mytest-m64.0000/cam4_s_base.mytest-m64 > cam4_s_base.mytest-m64.txt 2>> cam4_s_base.mytest-m64.err"
        ],
    },
    "628": {
        "name": "628.pop2_s",
        "commands": [
            "../run_base_test_mytest-m64.0000/speed_pop2_base.mytest-m64 > pop2_s.out 2>> pop2_s.err"
        ],
    },
    "638": {
        "name": "638.imagick_s",
        "commands": [
            "../run_base_test_mytest-m64.0000/imagick_s_base.mytest-m64 -limit disk 0 test_input.tga -shear 25 -resize 640x480 -negate -alpha Off test_output.tga > test_convert.out 2>> test_convert.err"
        ],
    },
    "644": {
        "name": "644.nab_s",
        "commands": [
            "../run_base_test_mytest-m64.0000/nab_s_base.mytest-m64 hkrdenq 1930344093 1000 > hkrdenq.out 2>> hkrdenq.err"
        ],
    },
    "649": {
        "name": "649.fotonik3d_s",
        "commands": [
            "../run_base_test_mytest-m64.0000/fotonik3d_s_base.mytest-m64 > fotonik3d_s.log 2>> fotonik3d_s.err"
        ],
    },
    "654": {
        "name": "654.roms_s",
        "commands": [
            "../run_base_test_mytest-m64.0000/sroms_base.mytest-m64 < ocean_benchmark0.in > ocean_benchmark0.log 2>> ocean_benchmark0.err"
        ],
    },
}

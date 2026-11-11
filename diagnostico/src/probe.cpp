// Medicao do computador e calculo da nota.
#include "probe.h"

#include <dxgi.h>
#include <dshow.h>
#include <shlobj.h>
#include <algorithm>
#include <cmath>
#include <cwctype>

// A referencia: o notebook em que o Morpho foi medido (RTX 3060 de 6 GB, i7-11800H).
// La, cada quadro em 720p custa 15,5 ms na placa de video (a troca) e 9 ms no
// processador (deteccao, rastreamento, composicao): cerca de 40 quadros por segundo
// de capacidade. As outras placas entram por um fator de desempenho relativo, que e
// uma ESTIMATIVA: so a de referencia foi medida de verdade.
static const double REF_SWAP_MS = 15.5;
static const double REF_CPU_MS = 9.0;
static const double REF_BENCH_MS = 5.5;     // tempo do teste de processador no computador de referencia (medido la)
static const double FULL_SCORE_FPS = 45.0;  // capacidade que vale nota 100
static const double NO_TENSORRT_PENALTY = 1.6;

static std::wstring Upper(std::wstring text)
{
	std::transform(text.begin(), text.end(), text.begin(), [](wchar_t c) { return (wchar_t)towupper(c); });
	return text;
}

static bool Has(const std::wstring &text, const wchar_t *part) { return text.find(part) != std::wstring::npos; }

static std::wstring Trim(std::wstring text)
{
	while (!text.empty() && iswspace(text.back())) text.pop_back();
	size_t start = 0;
	while (start < text.size() && iswspace(text[start])) start++;
	return text.substr(start);
}

static std::wstring Number(double value, int decimals)
{
	wchar_t buffer[64];
	swprintf_s(buffer, L"%.*f", decimals, value);
	std::wstring text(buffer);
	std::replace(text.begin(), text.end(), L'.', L',');
	return text;
}

// ---- medicao ------------------------------------------------------------------------------

static volatile unsigned g_sink;

// Um trabalho fixo parecido com o que o app faz no processador (contas sobre uma imagem).
// O menor tempo de algumas repeticoes, em milissegundos.
static double CpuBench()
{
	const int W = 640, H = 360, N = W * H * 3;
	std::vector<unsigned char> a(N), b(N);
	for (int i = 0; i < N; i++) a[i] = (unsigned char)(((unsigned)i * 2654435761u) >> 24);
	LARGE_INTEGER frequency, start, end;
	QueryPerformanceFrequency(&frequency);
	double best = 1e9;
	for (int run = 0; run < 5; run++)
	{
		QueryPerformanceCounter(&start);
		for (int pass = 0; pass < 12; pass++)
		{
			const unsigned char *src = (pass & 1) ? b.data() : a.data();
			unsigned char *dst = (pass & 1) ? a.data() : b.data();
			for (int y = 1; y < H - 1; y++)
			{
				const int row = y * W * 3;
				for (int x = 3; x < (W - 1) * 3; x++)
				{
					const int i = row + x;
					dst[i] = (unsigned char)((src[i - 3] + src[i + 3] + src[i - W * 3] + src[i + W * 3] + 4 * src[i]) >> 3);
				}
			}
		}
		QueryPerformanceCounter(&end);
		g_sink += a[N / 2] + b[N / 3];
		best = (std::min)(best, (end.QuadPart - start.QuadPart) * 1000.0 / frequency.QuadPart);
	}
	return best;
}

static void MeasureGpus(Report &r)
{
	IDXGIFactory1 *factory = NULL;
	if (FAILED(CreateDXGIFactory1(__uuidof(IDXGIFactory1), (void **)&factory))) return;
	IDXGIAdapter1 *adapter = NULL;
	for (UINT index = 0; factory->EnumAdapters1(index, &adapter) != DXGI_ERROR_NOT_FOUND; index++)
	{
		DXGI_ADAPTER_DESC1 desc;
		if (SUCCEEDED(adapter->GetDesc1(&desc)) && !(desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE))
		{
			Gpu gpu;
			gpu.name = Trim(desc.Description);
			gpu.vendor = desc.VendorId;
			gpu.vram = desc.DedicatedVideoMemory;
			LARGE_INTEGER version;
			if (SUCCEEDED(adapter->CheckInterfaceSupport(__uuidof(IDXGIDevice), &version)))
			{
				const int c = HIWORD(version.LowPart), d = LOWORD(version.LowPart);
				wchar_t text[64];
				if (gpu.vendor == 0x10DE)
				{
					// A NVIDIA conta a versao nos cinco ultimos digitos: 32.0.15.9174 e o driver 591.74.
					gpu.driverNumber = (c % 10) * 10000 + d;
					swprintf_s(text, L"%d.%02d", gpu.driverNumber / 100, gpu.driverNumber % 100);
				}
				else
					swprintf_s(text, L"%d.%d.%d.%d", HIWORD(version.HighPart), LOWORD(version.HighPart), c, d);
				gpu.driver = text;
			}
			bool repeated = false;   // a mesma placa aparece uma vez por saida de video em alguns sistemas
			for (const Gpu &other : r.gpus) repeated = repeated || (other.name == gpu.name && other.vram == gpu.vram);
			if (!repeated) r.gpus.push_back(gpu);
		}
		adapter->Release();
	}
	factory->Release();
	for (size_t i = 0; i < r.gpus.size(); i++)
		if (r.gpus[i].vendor == 0x10DE && (r.nvidia < 0 || r.gpus[i].vram > r.gpus[r.nvidia].vram)) r.nvidia = (int)i;
}

static void MeasureCameras(Report &r)
{
	const bool initialized = SUCCEEDED(CoInitializeEx(NULL, COINIT_APARTMENTTHREADED));
	ICreateDevEnum *devices = NULL;
	if (SUCCEEDED(CoCreateInstance(CLSID_SystemDeviceEnum, NULL, CLSCTX_INPROC_SERVER, IID_ICreateDevEnum, (void **)&devices)))
	{
		IEnumMoniker *list = NULL;
		if (devices->CreateClassEnumerator(CLSID_VideoInputDeviceCategory, &list, 0) == S_OK && list)
		{
			IMoniker *moniker = NULL;
			while (list->Next(1, &moniker, NULL) == S_OK)
			{
				IPropertyBag *bag = NULL;
				if (SUCCEEDED(moniker->BindToStorage(NULL, NULL, IID_IPropertyBag, (void **)&bag)))
				{
					VARIANT name;
					VariantInit(&name);
					if (SUCCEEDED(bag->Read(L"FriendlyName", &name, NULL)) && name.vt == VT_BSTR)
					{
						// Cameras virtuais (a do proprio Morpho, a do OBS...) nao contam como webcam.
						const std::wstring upper = Upper(name.bstrVal);
						if (!Has(upper, L"VIRTUAL") && !Has(upper, L"MORPHO") && !Has(upper, L"OBS") &&
							!Has(upper, L"BROADCAST") && !Has(upper, L"QUEST") && !Has(upper, L"SNAP CAMERA"))
							r.cameras.push_back(name.bstrVal);
					}
					VariantClear(&name);
					bag->Release();
				}
				moniker->Release();
			}
			list->Release();
		}
		devices->Release();
	}
	if (initialized) CoUninitialize();
}

Report Measure()
{
	Report r;

	typedef LONG(WINAPI * RtlGetVersionFunction)(OSVERSIONINFOW *);
	OSVERSIONINFOW version = {sizeof(version)};
	HMODULE ntdll = GetModuleHandleW(L"ntdll.dll");
	RtlGetVersionFunction getVersion = ntdll ? (RtlGetVersionFunction)GetProcAddress(ntdll, "RtlGetVersion") : NULL;
	if (getVersion && getVersion(&version) == 0)
	{
		r.winMajor = version.dwMajorVersion;
		r.winBuild = version.dwBuildNumber;
	}
	USHORT process = 0, native = 0;
	if (IsWow64Process2(GetCurrentProcess(), &process, &native)) r.arm = (native == IMAGE_FILE_MACHINE_ARM64);

	MeasureGpus(r);

	wchar_t cpu[256] = L"";
	DWORD size = sizeof(cpu);
	RegGetValueW(HKEY_LOCAL_MACHINE, L"HARDWARE\\DESCRIPTION\\System\\CentralProcessor\\0", L"ProcessorNameString",
				 RRF_RT_REG_SZ, NULL, cpu, &size);
	r.cpu = Trim(cpu);
	r.threads = (int)GetActiveProcessorCount(ALL_PROCESSOR_GROUPS);
	DWORD length = 0;
	GetLogicalProcessorInformationEx(RelationProcessorCore, NULL, &length);
	if (length)
	{
		std::vector<BYTE> buffer(length);
		if (GetLogicalProcessorInformationEx(RelationProcessorCore, (PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX)buffer.data(), &length))
			for (DWORD offset = 0; offset < length;)
			{
				PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX item = (PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX)(buffer.data() + offset);
				r.cores++;
				offset += item->Size;
			}
	}
	if (r.cores == 0) r.cores = r.threads;
	r.cpuMillis = CpuBench();
	r.cpuFactor = (std::min)(4.0, (std::max)(0.6, r.cpuMillis / REF_BENCH_MS));

	ULONGLONG installedKb = 0;
	if (GetPhysicallyInstalledSystemMemory(&installedKb)) r.ram = installedKb * 1024ull;
	else
	{
		MEMORYSTATUSEX memory = {sizeof(memory)};
		if (GlobalMemoryStatusEx(&memory)) r.ram = memory.ullTotalPhys;
	}

	// O disco em que o app sera instalado (a pasta do usuario).
	PWSTR folder = NULL;
	if (SUCCEEDED(SHGetKnownFolderPath(FOLDERID_LocalAppData, 0, NULL, &folder)) && folder && folder[0])
	{
		r.disk = (wchar_t)towupper(folder[0]);
		wchar_t root[4] = {folder[0], L':', L'\\', 0};
		ULARGE_INTEGER freeBytes;
		if (GetDiskFreeSpaceExW(root, &freeBytes, NULL, NULL)) r.diskFree = freeBytes.QuadPart;
	}
	if (folder) CoTaskMemFree(folder);

	MeasureCameras(r);

	wchar_t system[MAX_PATH];
	if (GetSystemDirectoryW(system, MAX_PATH))
		r.driverTools = GetFileAttributesW((std::wstring(system) + L"\\nvidia-smi.exe").c_str()) != INVALID_FILE_ATTRIBUTES;

	Evaluate(r);
	return r;
}

// ---- avaliacao ----------------------------------------------------------------------------

static int ModelNumber(const std::wstring &upper)
{
	for (size_t i = 0; i + 3 < upper.size(); i++)
		if (iswdigit(upper[i]) && iswdigit(upper[i + 1]) && iswdigit(upper[i + 2]) && iswdigit(upper[i + 3]) &&
			(i == 0 || !iswdigit(upper[i - 1])) && (i + 4 >= upper.size() || !iswdigit(upper[i + 4])))
			return (upper[i] - L'0') * 1000 + (upper[i + 1] - L'0') * 100 + (upper[i + 2] - L'0') * 10 + (upper[i + 3] - L'0');
	return 0;
}

// Desempenho da placa em relacao a RTX 3060 de notebook (= 1,0). Valores aproximados,
// de comparacoes publicas entre placas; "known" diz se o modelo esta na tabela.
static double ModelPower(const std::wstring &name, ULONGLONG vram, bool &known, bool &tensorRT)
{
	const std::wstring u = Upper(name);
	const int model = ModelNumber(u);
	const bool workstation = Has(u, L"RTX A") || Has(u, L"QUADRO") || Has(u, L" ADA");
	double power = 0;
	known = true;
	tensorRT = true;
	if (Has(u, L"RTX") && !workstation)
		switch (model)
		{
			case 5090: power = 5.3; break;  case 5080: power = 3.8; break;  case 5070: power = 2.7; break;
			case 5060: power = 1.8; break;  case 5050: power = 1.3; break;
			case 4090: power = 4.1; break;  case 4080: power = 3.1; break;  case 4070: power = 2.1; break;
			case 4060: power = 1.4; break;  case 4050: power = 1.1; break;
			case 3090: power = 2.7; break;  case 3080: power = 2.35; break; case 3070: power = 1.75; break;
			case 3060: power = 1.18; break; case 3050: power = 0.85; break;
			case 2080: power = 1.5; break;  case 2070: power = 1.2; break;  case 2060: power = 1.0; break;
			case 2050: power = 0.6; break;
			default: known = false;
		}
	else if (Has(u, L"GTX"))
		switch (model)
		{
			case 1660: power = 0.6; break;  case 1650: power = 0.4; break;  case 1630: power = 0.25; break;
			// A serie 10 nao tem os recursos do TensorRT no pacote: roda pelo caminho mais lento.
			case 1080: power = 0.65; tensorRT = false; break;
			case 1070: power = 0.5; tensorRT = false; break;
			case 1060: power = 0.35; tensorRT = false; break;
			case 1050: power = 0.22; tensorRT = false; break;
			default: known = false;
		}
	else if (Has(u, L"RTX A"))
		switch (model)
		{
			case 6000: power = 2.7; break;  case 5500: power = 2.5; break;  case 5000: power = 2.4; break;
			case 4500: power = 2.2; break;  case 4000: power = 1.9; break;  case 3000: power = 1.4; break;
			case 2000: power = 1.05; break; case 1000: power = 0.75; break;
			default: known = false;
		}
	else if (Has(u, L" MX") || Has(u, L"GT "))
		power = 0.2;
	else
		known = false;

	if (known)
	{
		if (Has(u, L" TI")) power *= 1.18;
		if (Has(u, L"SUPER")) power *= 1.10;
		if (Has(u, L"LAPTOP") || Has(u, L"MAX-Q") || Has(u, L"MOBILE")) power *= 0.85;
		return power;
	}
	// Modelo fora da tabela: a memoria de video da uma ideia da categoria.
	const double gb = (double)vram / GB;
	return gb >= 20 ? 2.5 : gb >= 14 ? 2.0 : gb >= 10 ? 1.6 : gb >= 7.5 ? 1.2 : gb >= 5.5 ? 0.9 : gb >= 3.5 ? 0.45 : 0.2;
}

void Evaluate(Report &r)
{
	r.checks.clear();
	Check check;

	// Sistema
	check = Check();
	check.title = L"Sistema";
	if (r.arm)
	{
		check.level = FAIL;
		check.detail = L"Windows em processador ARM: o Morpho precisa de um processador Intel ou AMD.";
	}
	else if (r.winMajor < 10 || r.winBuild < MIN_BUILD)
	{
		check.level = FAIL;
		check.detail = L"Windows antigo demais. O Morpho precisa do Windows 10 (versão 1809 ou mais nova) ou do Windows 11.";
	}
	else
		check.detail = std::wstring(r.winBuild >= 22000 ? L"Windows 11" : L"Windows 10") + L", 64 bits";
	r.checks.push_back(check);
	bool blocked = check.level == FAIL;

	// Placa de video
	check = Check();
	check.title = L"Placa de vídeo";
	bool tensorRT = true;
	double vramGb = 0;
	if (r.nvidia < 0)
	{
		check.level = FAIL;
		check.detail = L"Nenhuma placa NVIDIA encontrada";
		if (!r.gpus.empty()) check.detail += L" (este computador tem: " + r.gpus[0].name + L")";
		check.detail += L". O Morpho só funciona com placa NVIDIA.";
		blocked = true;
	}
	else
	{
		const Gpu &gpu = r.gpus[r.nvidia];
		vramGb = (double)gpu.vram / GB;
		r.gpuPower = ModelPower(gpu.name, gpu.vram, r.knownModel, tensorRT);
		check.detail = gpu.name;
		if (!tensorRT)
		{
			check.level = WARN;
			check.detail += L". Placa antiga: funciona num modo mais lento, que ainda não foi testado.";
		}
		else if (!r.knownModel)
			check.detail += L" (modelo fora da nossa tabela: a nota é estimada pela memória de vídeo)";
	}
	r.checks.push_back(check);

	// Memoria de video
	if (r.nvidia >= 0)
	{
		check = Check();
		check.title = L"Memória de vídeo";
		check.detail = Number(vramGb, vramGb < 10 ? 1 : 0) + L" GB";
		if (vramGb < MIN_VRAM_GB)
		{
			check.level = FAIL;
			check.detail += L". É pouco: os modelos do Morpho precisam de 4 GB, e o ideal são 6 GB.";
			blocked = true;
		}
		else if (vramGb < GOOD_VRAM_GB)
		{
			check.level = WARN;
			check.detail += L". Está no limite: use a qualidade Leve e feche jogos e outros programas pesados.";
		}
		r.checks.push_back(check);

		check = Check();
		check.title = L"Driver da NVIDIA";
		const Gpu &gpu = r.gpus[r.nvidia];
		check.detail = gpu.driver.empty() ? L"versão não identificada" : L"versão " + gpu.driver;
		if (!r.driverTools)
		{
			check.level = WARN;
			check.detail += L". O driver parece incompleto: instale o driver mais novo pelo site da NVIDIA.";
		}
		else if (gpu.driverNumber > 0 && gpu.driverNumber < 56000)
		{
			check.level = WARN;
			check.detail += L". Está desatualizado: instale o driver mais novo pelo site da NVIDIA antes de usar.";
		}
		r.checks.push_back(check);
	}

	// Processador
	check = Check();
	check.title = L"Processador";
	check.detail = (r.cpu.empty() ? std::wstring(L"não identificado") : r.cpu) + L" · " + std::to_wstring(r.cores) +
				   (r.cores == 1 ? L" núcleo" : L" núcleos");
	if (r.cpuFactor > 2.2 || r.threads < 4)
	{
		check.level = WARN;
		check.detail += L". É ele que vai limitar a velocidade.";
	}
	r.checks.push_back(check);

	// Memoria
	check = Check();
	check.title = L"Memória";
	const double ramGb = (double)r.ram / GB;
	check.detail = Number(ramGb, 0) + L" GB";
	if (ramGb < 7.5)
	{
		check.level = WARN;
		check.detail += L". É pouco: o recomendado são 16 GB. Feche outros programas ao usar.";
	}
	r.checks.push_back(check);

	// Disco
	check = Check();
	check.title = L"Espaço em disco";
	const double freeGb = (double)r.diskFree / GB;
	check.detail = Number(freeGb, 0) + L" GB livres no disco " + std::wstring(1, r.disk) + L":";
	if (freeGb < NEED_DISK_GB)
	{
		check.level = WARN;
		check.detail += L". Libere espaço: o download e a instalação precisam de " + Number(NEED_DISK_GB, 0) + L" GB.";
	}
	r.checks.push_back(check);

	// Webcam
	check = Check();
	check.title = L"Webcam";
	if (r.cameras.empty())
	{
		check.level = WARN;
		check.detail = L"Nenhuma webcam encontrada. Conecte uma antes de usar o Morpho.";
	}
	else
	{
		check.detail = r.cameras[0];
		if (r.cameras.size() > 1) check.detail += L" e mais " + std::to_wstring(r.cameras.size() - 1);
	}
	r.checks.push_back(check);

	// Nota
	r.compatible = !blocked;
	if (!r.compatible)
	{
		r.score = 0;
		r.fps = 0;
		r.grade = L"Não compatível";
		r.verdict = L"Este computador não roda o Morpho.";
		for (const Check &item : r.checks)
			if (item.level == FAIL)
			{
				r.advice = item.detail;
				break;
			}
		return;
	}
	const double frame = REF_SWAP_MS / r.gpuPower * (tensorRT ? 1.0 : NO_TENSORRT_PENALTY) + REF_CPU_MS * r.cpuFactor;
	r.fps = 1000.0 / frame;
	double score = 100.0 * (std::min)(1.0, r.fps / FULL_SCORE_FPS);
	if (vramGb < GOOD_VRAM_GB) score -= 15;
	if (ramGb < 7.5) score -= 10;
	r.score = (int)std::lround((std::max)(5.0, (std::min)(100.0, score)));
	r.grade = r.score >= 85 ? L"Excelente" : r.score >= 70 ? L"Muito bom" : r.score >= 50 ? L"Bom" : r.score >= 30 ? L"Limitado" : L"Fraco";
	r.verdict = r.score >= 50 ? L"Este computador roda o Morpho." : L"Este computador roda o Morpho, com limitações.";
	const int shown = (int)(std::min)(60.0, std::floor(r.fps / 5.0) * 5.0);
	if (r.fps >= 28)
		r.advice = L"Deve manter 30 quadros por segundo em 720p, o máximo da maioria das webcams.";
	else if (r.fps >= 15)
		r.advice = L"Deve fazer cerca de " + std::to_wstring((std::max)(15, shown)) + L" quadros por segundo em 720p. A qualidade Leve ajuda.";
	else
		r.advice = L"Vai rodar devagar: cerca de " + std::to_wstring((int)std::lround(r.fps)) + L" quadros por segundo. Dá para testar, mas a imagem fica travada.";
	for (const Check &item : r.checks)
		if (item.level == WARN && (item.title == L"Espaço em disco" || item.title == L"Driver da NVIDIA"))
		{
			r.advice = item.title + L": " + item.detail;   // o que impede de instalar ou abrir vem primeiro
			break;
		}
}

Report Fake(const std::wstring &scenario)
{
	Report r;
	r.winMajor = 10;
	r.winBuild = 26100;
	r.cpu = L"Intel(R) Core(TM) i5-12400F";
	r.cores = 6;
	r.threads = 12;
	r.cpuFactor = 0.9;
	r.cpuMillis = 5.6;
	r.ram = 16 * GB;
	r.diskFree = 180 * GB;
	r.cameras.push_back(L"HD Webcam");
	r.driverTools = true;
	Gpu gpu;
	gpu.vendor = 0x10DE;
	gpu.driver = L"591.74";
	gpu.driverNumber = 59174;
	if (scenario == L"sem-nvidia")
	{
		gpu.name = L"AMD Radeon RX 6600";
		gpu.vendor = 0x1002;
		gpu.vram = 8 * GB;
		gpu.driver = L"31.0.24027.1012";
		gpu.driverNumber = 0;
		r.cpu = L"AMD Ryzen 5 5600";
	}
	else if (scenario == L"fraco")
	{
		gpu.name = L"NVIDIA GeForce GTX 1650";
		gpu.vram = 4 * GB;
		r.cpu = L"Intel(R) Core(TM) i5-9300H";
		r.cores = 4;
		r.threads = 8;
		r.cpuFactor = 1.5;
		r.ram = 8 * GB;
		r.diskFree = 9 * GB;
	}
	else if (scenario == L"top")
	{
		gpu.name = L"NVIDIA GeForce RTX 4070 SUPER";
		gpu.vram = 12 * GB;
	}
	else
	{
		gpu.name = L"NVIDIA GeForce RTX 3060 Laptop GPU";
		gpu.vram = 6 * GB;
		r.cpu = L"11th Gen Intel(R) Core(TM) i7-11800H";
		r.cores = 8;
		r.threads = 16;
		r.cpuFactor = 1.0;
	}
	r.gpus.push_back(gpu);
	if (gpu.vendor == 0x10DE) r.nvidia = 0;
	Evaluate(r);
	return r;
}

// ---- texto --------------------------------------------------------------------------------

static std::wstring Escape(const std::wstring &text)
{
	std::wstring out;
	for (wchar_t c : text)
	{
		if (c == L'"' || c == L'\\') out += L'\\';
		out += c;
	}
	return out;
}

std::wstring ToJson(const Report &r)
{
	std::wstring j = L"{\n";
	j += L" \"compatible\": " + std::wstring(r.compatible ? L"true" : L"false") + L",\n";
	j += L" \"score\": " + std::to_wstring(r.score) + L",\n";
	j += L" \"grade\": \"" + Escape(r.grade) + L"\",\n";
	j += L" \"fps\": " + Number(r.fps, 1).replace(Number(r.fps, 1).find(L','), 1, L".") + L",\n";
	j += L" \"gpu_power\": " + std::to_wstring(r.gpuPower) + L",\n";
	j += L" \"known_model\": " + std::wstring(r.knownModel ? L"true" : L"false") + L",\n";
	j += L" \"cpu_ms\": " + std::to_wstring(r.cpuMillis) + L",\n";
	j += L" \"cpu_factor\": " + std::to_wstring(r.cpuFactor) + L",\n";
	j += L" \"verdict\": \"" + Escape(r.verdict) + L"\",\n";
	j += L" \"advice\": \"" + Escape(r.advice) + L"\",\n";
	j += L" \"checks\": [\n";
	for (size_t i = 0; i < r.checks.size(); i++)
		j += L"  {\"title\": \"" + Escape(r.checks[i].title) + L"\", \"level\": " + std::to_wstring((int)r.checks[i].level) +
			 L", \"detail\": \"" + Escape(r.checks[i].detail) + L"\"}" + (i + 1 < r.checks.size() ? L",\n" : L"\n");
	j += L" ]\n}\n";
	return j;
}

std::wstring ToText(const Report &r)
{
	std::wstring text = L"Diagnóstico do Morpho\r\n";
	text += r.verdict + L"\r\n";
	if (r.compatible) text += L"Nota: " + std::to_wstring(r.score) + L" de 100 (" + r.grade + L")\r\n";
	text += r.advice + L"\r\n\r\n";
	for (const Check &check : r.checks)
		text += (check.level == OK ? L"[ok] " : check.level == WARN ? L"[atenção] " : L"[não serve] ") + check.title + L": " + check.detail + L"\r\n";
	return text;
}

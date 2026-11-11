// O que o diagnostico mede neste computador e como transforma isso numa nota.
#pragma once

#include <windows.h>
#include <string>
#include <vector>

struct Gpu
{
	std::wstring name;
	UINT vendor = 0;            // 0x10DE = NVIDIA
	ULONGLONG vram = 0;         // memoria dedicada, em bytes
	std::wstring driver;        // versao do driver, no formato da NVIDIA quando for dela (ex.: 591.74)
	int driverNumber = 0;       // a mesma versao como numero (59174), para comparar
};

enum Level { OK, WARN, FAIL };

struct Check
{
	std::wstring title;
	std::wstring detail;
	Level level = OK;
};

struct Report
{
	// medido
	DWORD winMajor = 0, winBuild = 0;
	bool arm = false;
	std::vector<Gpu> gpus;
	int nvidia = -1;            // indice da melhor placa NVIDIA, ou -1
	std::wstring cpu;
	int cores = 0, threads = 0;
	double cpuMillis = 0;       // tempo do teste de processador
	double cpuFactor = 1.0;     // em relacao ao computador de referencia (1 = igual, 2 = duas vezes mais lento)
	ULONGLONG ram = 0, diskFree = 0;
	wchar_t disk = L'C';
	std::vector<std::wstring> cameras;
	bool driverTools = false;   // nvidia-smi presente: driver completo instalado

	// avaliado
	std::vector<Check> checks;
	bool compatible = false;
	bool knownModel = false;
	double gpuPower = 0;        // desempenho da placa em relacao a de referencia (RTX 3060 de notebook = 1)
	double fps = 0;             // quadros por segundo estimados em 720p
	int score = 0;              // 0 a 100
	std::wstring grade;         // "Excelente", "Bom"...
	std::wstring verdict;       // a frase principal
	std::wstring advice;        // o que fazer
};

// Requisitos (os mesmos da pagina de download).
const ULONGLONG GB = 1024ull * 1024ull * 1024ull;
const double NEED_DISK_GB = 13.0;   // 4 GB do download + 8 GB instalado, com folga
const double MIN_VRAM_GB = 3.5;     // abaixo disto os modelos nao cabem
const double GOOD_VRAM_GB = 5.5;    // "6 GB" de fabrica aparecem como pouco menos
const DWORD MIN_BUILD = 17763;      // Windows 10 versao 1809

Report Measure();
void Evaluate(Report &r);
Report Fake(const std::wstring &scenario);   // resultados inventados, para testar a tela
std::wstring ToJson(const Report &r);
std::wstring ToText(const Report &r);

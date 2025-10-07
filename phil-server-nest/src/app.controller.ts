import {
  Body,
  Controller,
  Get,
  HostParam,
  Post,
  Query,
  UsePipes,
  ValidationPipe,
} from '@nestjs/common';
import { AppService } from './app.service';
import { CreateHelloDto } from './create-hello.dto';

@Controller({ host: ':truck.localhost' })
export class AppController {
  constructor(private readonly appService: AppService) {}

  @Get()
  async getHello(
    @HostParam('truck') truckName?: string,
    @Query('relative') relative?: string,
  ): Promise<any> {
    console.log('await call');
    const message = this.appService.getHello(truckName);
    return `${message} ${relative}`;
  }

  @Post()
  @UsePipes(new ValidationPipe({ transform: true }))
  createHello(@Body() createHelloDto: CreateHelloDto): void {
    console.log(createHelloDto.name);
  }
}
